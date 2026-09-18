"""§38b hybrid selection chain: model selector -> read -> frozen extractor.

Single-variable diagnostic on the frozen §37A Node pool. Only the selection
authority changes:

    frozen candidate pool (same canonical URL set as the offline replay)
      -> MODEL selector (<=2 picks, up to N attempts)
           - if no usable decision: deterministic fallback to the frozen rule
             read set (the model never has the power to end research empty)
      -> live read through the production reader (ActiveResearchGateway)
      -> frozen extractor (RuntimeEvidenceExtractor, same prompt/parser)
      -> layered acceptance: target_selected -> target_read ->
         target_fact_present -> extractor_relation -> supports

Everything else stays frozen; the production runtime is untouched. The artifact
records the two invariants the offline/online comparison needs:
``selector_input_candidate_set`` and ``selector_output_urls``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from tools.run_selector_replay import (  # noqa: E402
    DEFAULT_ANNOTATIONS,
    DEFAULT_PROBE,
    agreed_targets,
    build_pool,
    load_probe_cases,
    rule_selection,
)

SCHEMA_VERSION = "hybrid-selection-chain-v1"
DEFAULT_CASE = "rq1c-historical-current-node-modules"
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_READ_CHARS = 6000


@dataclass
class HybridAttempt:
    status: str = ""
    reason: str = ""
    output_count: int = 0
    empty_output: bool = False


@dataclass
class HybridChain:
    case_id: str
    question: str
    pool_urls: list[str] = field(default_factory=list)
    selector_input_candidate_set: list[str] = field(default_factory=list)
    selector_output_urls: list[str] = field(default_factory=list)
    selector_attempts: list[dict] = field(default_factory=list)
    selection_authority: str = ""
    picks: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    target_selected: bool = False
    reads: list[dict] = field(default_factory=list)
    extractions: list[dict] = field(default_factory=list)
    target_read: bool = False
    target_fact_relation: str = ""
    target_fact_present: bool | None = None
    supports: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "selector_input_candidate_set": list(self.selector_input_candidate_set),
            "selector_output_urls": list(self.selector_output_urls),
            "selector_input_size": len(self.selector_input_candidate_set),
            "selector_attempts": [dict(item) for item in self.selector_attempts],
            "selection_authority": self.selection_authority,
            "picks": list(self.picks),
            "targets": list(self.targets),
            "target_selected": self.target_selected,
            "reads": [dict(item) for item in self.reads],
            "extractions": [dict(item) for item in self.extractions],
            "target_read": self.target_read,
            "target_fact_relation": self.target_fact_relation,
            "target_fact_present": self.target_fact_present,
            "supports": self.supports,
        }


def run_chain(
    *,
    case_id: str,
    question: str,
    pool: list[dict],
    targets: list[str],
    rule_picks: list[str],
    selector: Callable[[str, list[dict], int], list[str]],
    reader: Callable[[str, int], Mapping[str, Any]],
    extractor: Callable[[str, Mapping[str, Any], str], Mapping[str, Any]],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_picks: int = 2,
    read_chars: int = DEFAULT_READ_CHARS,
) -> HybridChain:
    """One bounded hybrid pass; every collaborator is injectable."""

    chain = HybridChain(case_id=case_id, question=question)
    chain.pool_urls = [entry["url"] for entry in pool]
    chain.selector_input_candidate_set = list(chain.pool_urls)
    chain.targets = list(targets)

    attempts: list[dict] = []
    picks: list[str] = []
    for _ in range(max(1, max_attempts)):
        try:
            outcome = list(selector(question, pool, max_picks))[:max_picks]
        except Exception as exc:  # noqa: BLE001 - diagnostics never fatal
            outcome = []
            attempts.append(
                {"status": "exception", "reason": type(exc).__name__, "output_count": 0, "empty_output": True}
            )
        else:
            last = getattr(selector, "last_call", None)
            if isinstance(last, dict):
                attempts.append(dict(last))
            else:
                attempts.append(
                    {
                        "status": "completed",
                        "reason": "",
                        "output_count": len(outcome),
                        "empty_output": len(outcome) == 0,
                    }
                )
        if outcome:
            picks = outcome
            break
    chain.selector_attempts = attempts

    if picks:
        chain.selection_authority = "model"
    else:
        chain.selection_authority = "rule_fallback"
        picks = [url for url in rule_picks][:max_picks]

    chain.selector_output_urls = [entry["url"] for entry in pool if entry["url"] in set(picks)]
    if not chain.selector_output_urls:
        # Fallback picks may not be in the model pool (rule read set can come
        # from candidates the frozen pool dropped); keep them visible anyway.
        chain.selector_output_urls = list(picks)
    chain.picks = list(picks)
    chain.target_selected = any(target in picks for target in targets)

    for url in picks:
        entry = next((item for item in pool if item["url"] == url), {"url": url, "title": url})
        raw = dict(reader(url, read_chars) or {})
        content = str(raw.get("content") or "")[:read_chars]
        readable = bool(raw.get("ok") is True and content.strip())
        chain.reads.append(
            {
                "url": url,
                "ok": raw.get("ok") is True,
                "content_chars": len(content),
                "error": str(raw.get("error") or "")[:200],
            }
        )
        if url in targets and readable:
            chain.target_read = True
        if not readable:
            chain.extractions.append(
                {"url": url, "relation": "unreadable", "caveat": str(raw.get("error") or "empty_read")[:200]}
            )
            continue
        extraction = extractor(question, entry, content) or {}
        relation = str(extraction.get("relation") or "unavailable")
        chain.extractions.append(
            {
                "url": url,
                "relation": relation,
                "caveat": str(extraction.get("caveat") or "")[:300],
            }
        )
        if relation == "supports":
            chain.supports += 1
        if url in targets:
            chain.target_fact_relation = relation
            if relation in {"supports", "qualifies"}:
                chain.target_fact_present = True
            elif relation in {"lead", "background"}:
                chain.target_fact_present = False
            else:
                chain.target_fact_present = None
    return chain


# ---------------------------------------------------------------------------
# Production-backed adapters.
# ---------------------------------------------------------------------------


def _resolved_model_name() -> str:
    try:
        from src.llm_client import get_model_name

        return get_model_name("flash")
    except Exception:
        return ""


def build_adapters(
    *, model_timeout_seconds: float = 30.0
) -> tuple[
    Callable[[str, list[dict], int], list[str]],
    Callable[[str, int], Mapping[str, Any]],
    Callable[[str, Mapping[str, Any], str], Mapping[str, Any]],
    Callable[[], dict],
]:
    from src.web.research.active_adapter import ActiveResearchGateway
    from src.web.research.active_semantics import RuntimeEvidenceExtractor
    from src.web.research.contracts import EvidenceRequirement, ResearchClaim
    from src.web.research.model_gateway import ResearchModelGateway
    from tools.run_agent_loop_prototype import SELECTOR_SYSTEM_PROMPT, _parse_selector

    gateway = ActiveResearchGateway()
    model = ResearchModelGateway(model_profile="flash", timeout_seconds=model_timeout_seconds)
    extractor = RuntimeEvidenceExtractor(model)
    state: dict[str, Any] = {"claim": None, "call_count": 0}

    def claim_for(question: str) -> Any:
        claim = state.get("claim")
        if claim is None or claim.text != question:
            claim = ResearchClaim(
                id="claim_hybrid_chain",
                question_id="question_hybrid_chain",
                text=question[:2000],
                kind="factual",
                priority="critical",
                state="pending",
                evidence_requirement=EvidenceRequirement(requires_successful_read=True),
                created_by="hybrid_selection_chain",
                created_reason="§38b diagnostic chain",
            )
            state["claim"] = claim
        return claim

    def selector(question: str, pool: list[dict], max_picks: int) -> list[str]:
        state["call_count"] += 1
        call_id = f"hybrid_selector:{state['call_count']}"
        payload = {"question": question, "max_urls": max_picks, "candidates": pool}
        result = model.complete_structured(
            logical_call_id=call_id,
            purpose="hybrid_selection",
            messages=[
                {"role": "system", "content": SELECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            audit_payload=payload,
            response_schema_version="hybrid-selection-v1",
            parse=_parse_selector,
            data_categories=("public_research_claim", "public_candidate_metadata"),
            max_tokens=500,
        )
        status = str(getattr(result, "status", ""))
        reason = str(getattr(result, "reason", "") or "")
        value = result.value if status == "completed" else None
        selector.last_call = {  # type: ignore[attr-defined]
            "status": status,
            "reason": reason,
            "output_count": len(list(value)) if value is not None else 0,
            "empty_output": value is None or len(list(value)) == 0,
        }
        if value is None:
            return []
        pool_urls = {entry["url"] for entry in pool}
        picks: list[str] = []
        for item in list(value):
            candidate = str(item).strip()
            canonical = candidate if candidate in pool_urls else ""
            if canonical and canonical not in picks:
                picks.append(canonical)
            if len(picks) >= max_picks:
                break
        return picks

    def reader(url: str, max_chars: int) -> Mapping[str, Any]:
        return dict(gateway.read(url, max_chars=max_chars) or {})

    def extractor_fn(question: str, entry: Mapping[str, Any], content: str) -> Mapping[str, Any]:
        from src.web.research.candidate_pool import CandidatePoolItem

        url = str(entry.get("url") or "")
        item = CandidatePoolItem(
            id=url,
            canonical_url=url,
            url=url,
            title=str(entry.get("title") or url)[:300],
            snippet="",
            source="hybrid_selection_chain",
            published_at="",
            query_ids=(),
            intents=(),
            providers=(),
            first_seen_rank=0,
        )
        result = extractor.extract(
            run_id="hybrid_selection_chain",
            claim=claim_for(question),
            candidate=item,
            source_role="primary",
            source_cluster_id="hybrid_cluster",
            content=content,
            timeout_seconds=model_timeout_seconds,
        )
        if result.status != "completed" or result.extraction is None:
            return {"relation": "unavailable", "caveat": result.reason or "extractor_unavailable"}
        link = result.extraction
        return {"relation": link.relation, "caveat": "; ".join(link.caveats or ())}

    def provenance() -> dict:
        import os

        return {
            "provider_profile": os.getenv("LLM_PROVIDER_PROFILE") or "openai",
            "model_profile": "flash",
            "model_name": _resolved_model_name(),
            "thinking_mode": "disabled_for_structured_research_calls",
        }

    return selector, reader, extractor_fn, provenance


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, default=DEFAULT_PROBE)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--case", default=DEFAULT_CASE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--max-picks", type=int, default=2)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    load_dotenv(REPO_ROOT / ".env")
    probe = json.loads(args.probe.read_text(encoding="utf-8"))
    annotations = json.loads(args.annotations.read_text(encoding="utf-8"))
    cases = [
        case
        for case in load_probe_cases(probe)
        if str(case.get("case_id")) == args.case
    ]
    if not cases:
        raise SystemExit(f"case not found in probe: {args.case}")
    case = cases[0]
    pool = build_pool(case)
    targets = agreed_targets(annotations, args.case)
    rule_picks, _rule_reasons = rule_selection(case)
    selector, reader, extractor_fn, provenance = build_adapters()
    chain = run_chain(
        case_id=args.case,
        question=str(case.get("question") or ""),
        pool=pool,
        targets=targets,
        rule_picks=rule_picks,
        selector=selector,
        reader=reader,
        extractor=extractor_fn,
        max_attempts=args.max_attempts,
        max_picks=args.max_picks,
    )
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "source_probe": str(args.probe).replace("\\", "/"),
        "annotations": str(args.annotations).replace("\\", "/"),
        "max_attempts": args.max_attempts,
        "max_picks": args.max_picks,
        "read_chars": DEFAULT_READ_CHARS,
        "assumptions": {
            "source_role": "primary_for_every_selected_page",
            "source_cluster_id": "single_constant_cluster",
            "claim": "one factual claim per case (the case question)",
            "note": "prototype simplification; relation semantics are the frozen "
            "extractor's own output, but cluster independence is not modelled",
        },
        "rule_picks": rule_picks,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **provenance(),
        "chain": chain.to_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    payload = chain.to_dict()
    print(
        json.dumps(
            {
                "case": payload["case_id"],
                "authority": payload["selection_authority"],
                "target_selected": payload["target_selected"],
                "target_read": payload["target_read"],
                "target_fact_relation": payload["target_fact_relation"],
                "target_fact_present": payload["target_fact_present"],
                "supports": payload["supports"],
                "attempts": payload["selector_attempts"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
