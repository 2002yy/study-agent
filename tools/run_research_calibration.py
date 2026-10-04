"""Explicit, bounded production diagnostic in a fresh database outside the repo.

Run manually, never in CI. Related source bodies are not proof of answer support.
Raw artifacts contain public sources and diagnostic answers, never API keys.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.active_research_runtime import ACTIVE_RESEARCH_METRICS_KEY  # noqa: E402


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def percentile(values: list[float], fraction: float) -> float | None:
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 3) if values else None


def summarize(rows: list[dict]) -> dict:
    groups = {}
    for tier in ("lookup", "standard"):
        for recovered in (False, True):
            selected = [row for row in rows if row["tier"] == tier and row["recovery_used"] == recovered]
            elapsed = [row["elapsed_seconds"] for row in selected]
            # This denominator is source availability, not semantic success.
            backed = [row["elapsed_seconds"] for row in selected if row["adopted_bodies"] > 0]
            groups[f"{tier}:{'recovery' if recovered else 'base'}"] = {
                "n": len(selected), "all_p50": percentile(elapsed, .5), "all_p95": percentile(elapsed, .95),
                "read_backed_n": len(backed), "read_backed_p50": percentile(backed, .5),
                "read_backed_p95": percentile(backed, .95),
                "stop_reasons": dict(Counter(row["stop_reason"] for row in selected)),
            }
    return {"groups": groups, "executions": len(rows), "qualified_judge": False,
            "question_coverage": "manual_review_required", "small_sample_percentiles": "observation_only"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/research_calibration_v1.json")
    parser.add_argument("--output", type=Path, required=True, help="New directory outside this repository")
    parser.add_argument("--cases", nargs="*", help="Optional bounded subset of frozen case IDs")
    parser.add_argument("--repetitions", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("Artifacts and diagnostic DB must be outside the repository")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    if len(cases) != 8 or len({case["id"] for case in cases}) != 8:
        parser.error("Expected eight unique frozen cases")
    if args.cases:
        if set(args.cases) - {case["id"] for case in cases}:
            parser.error("Unknown case ID")
        cases = [case for case in cases if case["id"] in args.cases]
    if len(cases) * args.repetitions > min(16, manifest["max_executions"]):
        parser.error("Execution cap exceeded")
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(ROOT))
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    os.environ["STUDY_AGENT_RUNTIME_DB"] = str(output / "runtime.db")
    os.environ["STUDY_AGENT_CURRENT_EXPORT_DIR"] = str(output / "current")
    os.environ["STUDY_AGENT_ARCHIVE_EXPORT_DIR"] = str(output / "archive")
    from src.application.policy_chat_service import PolicyChatCommand
    from src.application.runtime_repository import get_chat_service, get_web_lookup_service, get_web_tool_agent
    from src.llm_client import get_provider_settings
    from src.web.recovery_candidates import canonical_document, source_family
    from src.web.discovery import in_scope
    from src.web.semantic_recovery import configured_completion
    from src.web.tool_evidence import evidence_tool_calls

    settings = get_provider_settings()
    inference_events: list[dict] = []

    def observe(**kwargs):
        started = time.monotonic()
        event = {"stage": kwargs["task_name"], "started_at": datetime.now(timezone.utc).isoformat()}
        inference_events.append(event)
        try:
            response = configured_completion(**kwargs)
            event.update(response=response, response_sha256=sha(response))
            return response
        except Exception as exc:
            event["error_type"] = type(exc).__name__
            raise
        finally:
            event["elapsed_seconds"] = round(time.monotonic() - started, 3)

    agent = get_web_tool_agent()
    agent.semantic_completion = observe
    original_resolve = agent.resolve
    observed_traces = []

    def observe_resolve(*positional, **kwargs):
        value = original_resolve(*positional, **kwargs)
        observed_traces.append(value)
        return value

    agent.resolve = observe_resolve
    files = ["src/web/semantic_recovery.py", "src/web/research_recovery.py", "src/web/tool_evidence.py",
             "src/web/conversation_query.py", "src/web/tool_gateway.py", "src/web/discovery.py",
             "src/news/search_sources/searxng_source.py", "src/tools/persistent_web_agent.py", "src/application/chat_service.py",
             "src/application/policy_chat_service.py", "src/application/web_lookup_service.py"]
    result = {
        "schema_version": "research-calibration-result-v1", "qualified_judge": False,
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dirty_paths": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).splitlines(),
        "manifest": manifest, "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "selected_cases": [case["id"] for case in cases], "repetitions": args.repetitions,
        "provider": settings.profile_name, "model": settings.flash_model,
        "endpoint_host": urlparse(settings.base_url).hostname, "network_mode": "live",
        "production_file_digests": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in files},
        "runs": [], "semantic_inferences": inference_events,
    }

    def persist():
        result["summary"] = summarize(result["runs"])
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    persist()
    for repetition in range(args.repetitions):
        for case in cases:
            started = time.monotonic()
            started_at = datetime.now(timezone.utc).isoformat()
            event_offset = len(inference_events)
            trace_offset = len(observed_traces)
            prepared = None
            answer = ""
            failure = ""
            research_seconds = None
            generation_seconds = None
            try:
                chat = get_chat_service()
                prepared = chat.start_turn(PolicyChatCommand(
                    user_input=case["query"], thread_id=f"calibration-{case['id']}-{repetition}",
                    selected_model="flash", web_policy="auto", cloud_context_policy="recent_chat", rag_enabled=False,
                ))
                research_seconds = round(time.monotonic() - started, 3)
                generation_started = time.monotonic()
                try:
                    answer = chat.generate(prepared)
                finally:
                    generation_seconds = round(time.monotonic() - generation_started, 3)
            except Exception as exc:
                failure = type(exc).__name__
                if prepared is not None:
                    try:
                        chat.fail_turn(prepared)
                    except Exception:
                        pass  # Preserve the original failure and completed trace.
            trace = prepared.rag.get("web_tools", {}) if prepared else {}
            raw_calls = list(observed_traces[-1].calls) if len(observed_traces) > trace_offset else []
            episode = None
            if trace.get("run_id"):
                run = get_web_lookup_service().get(trace["run_id"])
                episode = run.research_context.get("semantic_episode")
            reads = [call for call in raw_calls if call.get("name") == "web_read"]
            searches = [call for call in raw_calls if call.get("name") == "web_search"]
            adopted = evidence_tool_calls(raw_calls)
            planned_queries = []
            for event in inference_events[event_offset:]:
                if event["stage"] == "research_turn_interpretation" and event.get("response"):
                    try:
                        planned_queries = json.loads(event["response"]).get("proposed_queries", [])
                    except (ValueError, AttributeError):
                        pass
            provider_counts = {}
            provider_urls = {}
            for search in searches:
                for stat in search.get("result", {}).get("provider_stats", []):
                    name = stat["provider"]
                    entry = provider_counts.setdefault(name, {"attempted": 0, "results": 0, "unique_urls": 0,
                                                              "bodies_read": 0, "bodies_adopted": 0, "reasons": []})
                    entry["attempted"] += int(stat.get("attempted", False))
                    entry["results"] += stat.get("results", 0)
                    entry["reasons"].append(stat.get("reason", ""))
                    provider_urls.setdefault(name, set()).update(stat.get("urls", []))
            adopted_requested = {call.get("arguments", {}).get("url") for call in adopted}
            official_domains = tuple(case.get("official_domains", []))
            candidates_all = [item for search in searches for item in search.get("result", {}).get("results", [])]
            def expected_publisher_url(url):
                if any(in_scope(url, domain) for domain in official_domains):
                    return True
                parsed = urlparse(url)
                for prefix in case.get("official_url_prefixes", []):
                    expected = urlparse(prefix)
                    if parsed.hostname == expected.hostname and (parsed.path.rstrip("/") == expected.path.rstrip("/")
                            or parsed.path.startswith(expected.path.rstrip("/") + "/")):
                        return True
                return False

            official_urls = {item["url"] for item in candidates_all if expected_publisher_url(item.get("url", ""))}
            official_reads = [call for call in reads if call.get("arguments", {}).get("url") in official_urls]
            official_adopted = [call for call in adopted if call.get("arguments", {}).get("url") in official_urls]
            for name, entry in provider_counts.items():
                discovered = provider_urls[name]
                entry["unique_urls"] = len(discovered)
                entry["bodies_read"] = sum(call.get("arguments", {}).get("url") in discovered for call in reads)
                entry["bodies_adopted"] = len(adopted_requested & discovered)
            recovery = trace.get("recovery") or {}
            scheduler = recovery.get("candidate_scheduler") or {}
            urls = [call["arguments"]["url"] for call in reads]
            completed_reads = [call["result"]["read_completed_at"] for call in reads
                               if call["result"].get("ok") is True and call["result"].get("read_completed_at")]
            first_successful = min(completed_reads) if completed_reads else None
            row = {
                "case_id": case["id"], "repetition": repetition + 1, "tier": case["tier"],
                "started_at": started_at, "completed_at": datetime.now(timezone.utc).isoformat(),
                "query": case["query"], "expected_aspects": case["aspects"], "error_type": failure,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "research_seconds": research_seconds, "finalization_seconds": generation_seconds,
                "first_successful_read_seconds": round((datetime.fromisoformat(first_successful)
                    - datetime.fromisoformat(started_at)).total_seconds(), 3) if first_successful else None,
                "provider_metrics": provider_counts,
                "official_candidate_found": bool(official_urls), "official_candidate_urls": sorted(official_urls),
                "official_bodies_read": len(official_reads), "official_bodies_adopted": len(official_adopted),
                "question_covered": "manual_review_required",
                "domain_diversity": len({source_family(item.get("url", "")) for item in candidates_all}),
                "queries_planned": len(planned_queries), "query_plan": planned_queries,
                "raw_results": sum(v["results"] for v in provider_counts.values()),
                "unique_urls": len(set().union(*provider_urls.values())) if provider_urls else 0,
                "candidate_count": sum(len(call.get("result", {}).get("results", [])) for call in searches),
                "attempted_reads": len(reads), "successful_reads": sum(call["result"].get("ok") is True for call in reads),
                "adopted_bodies": len(adopted), "unique_canonical_docs": len({canonical_document(url) for url in urls}),
                "unique_source_families": len({source_family(url) for url in urls}),
                "unique_final_canonical_docs": len({canonical_document(call["result"].get("url") or call["arguments"]["url"]) for call in reads}),
                "recovery_used": bool(recovery.get("recovery_reads") or len(searches) > 1),
                "recovery_reads": recovery.get("recovery_reads", 0), "scheduler": scheduler,
                "stop_reason": recovery.get("stop_reason", "NO_RECOVERY_TRACE"),
                # §174.3.1 observation-only: per-candidate reasons + zero-read
                # summary, so a later zero-read run is explainable offline.
                "candidate_resolution_trace": (
                    (getattr(run, "research_context", {}) or {}).get(
                        ACTIVE_RESEARCH_METRICS_KEY
                    )
                    or {}
                ).get("candidate_resolution_trace") or {},
                "semantic_calls": len(inference_events) - event_offset,
                "writer_calls": prepared.route.get("answer_generation_calls", 0) if prepared else 0,
                "question_coverage": "not_semantically_evaluated", "answer": answer, "answer_sha256": sha(answer),
                "trace": trace, "raw_calls": raw_calls, "episode": episode,
            }
            result["runs"].append(row)
            persist()
            print(json.dumps({key: row[key] for key in (
                "case_id", "repetition", "elapsed_seconds", "attempted_reads", "adopted_bodies", "stop_reason", "error_type"
            )}, ensure_ascii=True), flush=True)
    print(str(output / "result.json"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
