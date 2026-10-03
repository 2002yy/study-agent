# -*- coding: utf-8 -*-
"""§143-RS read-site qualification (operator, real Crawl4AI worker).

Proves the full chain ``WebLookupService.create -> run context -> execute()
read-site selector -> real Crawl4AI worker`` without touching production
loopback/SSRF policy. The fixture candidate is injected by an **operator/test
seam** *after* production candidate validation (``execute_candidate_pool_batch``
output) and *before* the read site, so this qualification does not re-qualify
search / candidate resolution / URL safety.

Three cases:
  Q1 specialist usable      -> default run_chain call count == 0
  Q2 specialist unusable    -> hint_honored=true, fallback_used=true, default chain runs
  Q3 specialist not run     -> hint_honored=false + reason, default chain runs

Usage (operator, real worker)::

    set CRAWL4AI_PYTHON=<isolated interpreter>
    python tools/run_read_site_qualification.py --output docs/research_quality/READ_SITE_QUALIFICATION.json
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

RUNTIME_TEST = REPO_ROOT / "tests" / "test_active_research_runtime.py"
FIXTURE = REPO_ROOT / "tools" / "f2_paired_fixture_server.py"
PORT = 8804
JS_RENDER = "JS_RENDER"


def _load_test_module() -> Any:
    spec = importlib.util.spec_from_file_location("_art_qual", RUNTIME_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wait(base: str, deadline: float = 20.0) -> bool:
    end = time.time() + deadline
    while time.time() < end:
        try:
            urllib.request.urlopen(f"{base}/structured-spec.html", timeout=2).read(8)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def _chain(completed: Any, art: Any) -> list[dict[str, Any]]:
    metrics = completed.research_context.get(art.ACTIVE_RESEARCH_METRICS_KEY) or {}
    return [
        {
            "action": row.get("action"),
            "steps": [step.get("backend") for step in (row.get("steps") or [])],
        }
        for row in (metrics.get("read_chain") or [])
    ]


def _specialist_provenance(completed: Any, art: Any) -> list[dict[str, Any]]:
    metrics = completed.research_context.get(art.ACTIVE_RESEARCH_METRICS_KEY) or {}
    return list(metrics.get("read_site_specialist") or [])


def _run_case(
    art: Any,
    *,
    case: str,
    fixture_path: str,
    base: str,
    tmp_dir: Path,
    hints_enabled: bool,
    run_chain_counter: dict[str, int],
) -> dict[str, Any]:
    from src.application import active_research_runtime as runtime
    from src.application.research_web_lookup_dispatch import (
        ClaimEngineDispatchWebLookupService,
    )
    from src.web.research.candidate_pool import CandidatePoolItem
    from src.web.research.model_gateway import ResearchModelGateway

    os.environ["EXPLICIT_READER_HINTS_ENABLED"] = "1" if hints_enabled else "0"

    fixture_url = f"{base}{fixture_path}"
    original_batch = runtime.execute_candidate_pool_batch

    def injected_batch(batch, **kwargs):
        result = original_batch(batch, **kwargs)
        query = batch.queries[0] if batch.queries else None
        fixture = CandidatePoolItem(
            id="candidate_fixture_specialist",
            canonical_url=fixture_url,
            url=fixture_url,
            title="Fixture specialist target",
            snippet="Verified release announcement",
            source="fixture",
            published_at="2026-08-01",
            query_ids=(query.id,) if query else (),
            intents=(query.intent,) if query else (),
            providers=("searxng",),
            first_seen_rank=1000,
        )
        return dataclasses.replace(result, candidates=(*result.candidates, fixture))

    runtime.execute_candidate_pool_batch = injected_batch  # operator/test seam
    original_run_chain = runtime.run_chain

    def counting_run_chain(*args, **kwargs):
        run_chain_counter["calls"] += 1
        return original_run_chain(*args, **kwargs)

    runtime.run_chain = counting_run_chain

    repository = art._TrackingRepository(art.RuntimeDatabase(tmp_dir / f"{case}.sqlite"))
    # Deterministic active run with the explicit hint already on its context.
    # (Transport recording via WebLookupService.create is proven separately in
    # tests/test_read_site_selector.py; create() does not seed an active state.)
    context = art._active_context()
    context["reader_capabilities"] = [JS_RENDER]
    context["reader_capabilities_source"] = "REQUEST_FIELD"
    created = repository.create(
        art.WebLookupRun(
            id=f"run_qual_{case}",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )
    run_id = created.id

    gateway = art.ActiveResearchGateway(
        search_backend=art._EmptySearchBackend(),
        read_gateway=art._ShortNativeReadGateway(text="z" * 1200),
    )
    gateway.set_escalation_backend(art._CutoverEscalationBackend("y" * 1200))

    def gf():
        return gateway

    def rf(repo, gw):
        model = ResearchModelGateway(
            client=art._PrimaryRoleClient(), model_name="test-model", timeout_seconds=20
        )
        return art.ActiveResearchRuntimeExecutor(
            repo, gw, model_gateway=model, monotonic=art.perf_counter
        )

    service = ClaimEngineDispatchWebLookupService(
        repository, active_gateway_factory=gf, active_runtime_factory=rf
    )
    completed = service.execute(run_id, raise_on_error=True)
    # restore the operator/test seam so the next case starts from production
    runtime.execute_candidate_pool_batch = original_batch
    runtime.run_chain = original_run_chain
    return {
        "case": case,
        "fixture": fixture_path,
        "chain": _chain(completed, art),
        "specialist_provenance": _specialist_provenance(completed, art),
        "run_chain_calls": run_chain_counter["calls"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="")
    args = ap.parse_args(argv)

    from src.web.research.crawl4ai_specialist import (
        configured_python,
        reset_crawl4ai_specialist,
    )

    if not configured_python():
        raise SystemExit("CRAWL4AI_PYTHON is not set; this is an operator qualification run")
    os.environ.setdefault("CRAWL4AI_SPECIALIST_ENABLED", "1")
    os.environ.setdefault("RESEARCH_WIGOLO_ESCALATION", "browser")
    os.environ.setdefault("WIGOLO_RERANKER", "off")

    server = subprocess.Popen(
        [sys.executable, "-u", "-X", "utf8", str(FIXTURE), "--port", str(PORT)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{PORT}"
    if not _wait(base):
        server.terminate()
        raise SystemExit("fixture server did not become ready")

    art = _load_test_module()
    tmp_dir = Path(tempfile.mkdtemp(prefix="read_site_qual_"))
    cases: dict[str, Any] = {}
    try:
        # Q1: real specialist usable
        counter = {"calls": 0}
        cases["Q1"] = _run_case(
            art, case="Q1", fixture_path="/structured-spec.html", base=base,
            tmp_dir=tmp_dir, hints_enabled=True, run_chain_counter=counter,
        )
        reset_crawl4ai_specialist()
        # Q2: real specialist executed but unusable (short page) -> fallback
        counter = {"calls": 0}
        cases["Q2"] = _run_case(
            art, case="Q2", fixture_path="/f2-fallback-sentinel.html", base=base,
            tmp_dir=tmp_dir, hints_enabled=True, run_chain_counter=counter,
        )
        reset_crawl4ai_specialist()
        # Q3: hint present but gate OFF -> specialist not executed
        counter = {"calls": 0}
        cases["Q3"] = _run_case(
            art, case="Q3", fixture_path="/structured-spec.html", base=base,
            tmp_dir=tmp_dir, hints_enabled=False, run_chain_counter=counter,
        )
    finally:
        reset_crawl4ai_specialist()
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()

    checks = {
        "Q1_specialist_short_circuits": (
            cases["Q1"]["run_chain_calls"] == 0
            and all(row["steps"] == ["crawl4ai_browser"] for row in cases["Q1"]["chain"])
            and cases["Q1"]["specialist_provenance"]
            and cases["Q1"]["specialist_provenance"][0]["specialist_usable"] is True
            and cases["Q1"]["specialist_provenance"][0]["hint_honored"] is True
            and cases["Q1"]["specialist_provenance"][0]["specialist_latency_ms"] > 0
        ),
        "Q2_specialist_executed_then_fallback": (
            cases["Q2"]["run_chain_calls"] > 0
            and cases["Q2"]["specialist_provenance"]
            and cases["Q2"]["specialist_provenance"][0]["specialist_attempted"] is True
            and cases["Q2"]["specialist_provenance"][0]["hint_honored"] is True
            and cases["Q2"]["specialist_provenance"][0]["specialist_usable"] is False
            and cases["Q2"]["specialist_provenance"][0]["fallback_used"] is True
            and cases["Q2"]["specialist_provenance"][0]["specialist_latency_ms"] > 0
            and all(row["steps"] and row["steps"][0] == "native_http" for row in cases["Q2"]["chain"])
        ),
        "Q3_gate_blocks_specialist": (
            cases["Q3"]["run_chain_calls"] > 0
            and cases["Q3"]["specialist_provenance"]
            and cases["Q3"]["specialist_provenance"][0]["hint_honored"] is False
            and cases["Q3"]["specialist_provenance"][0]["specialist_attempted"] is False
            and cases["Q3"]["specialist_provenance"][0]["specialist_unavailable_reason"]
            == "hints_disabled"
        ),
    }
    payload = {"schema": "read-site-qualification-v1", "cases": cases, "checks": checks}
    print(json.dumps(payload, indent=1, ensure_ascii=False))
    if args.output:
        out = Path(args.output)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
