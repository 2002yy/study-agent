# -*- coding: utf-8 -*-
"""§143-RS read-site parity harness (deterministic, no-provider).

Proves that the execute() inline read site is unchanged when no reader
capability hint is present. It drives the *real* production dispatch/runtime
through the deterministic fakes already used by
``tests/test_active_research_runtime.py`` (no broad research runner, no network)
and captures only stable, machine-comparable observations.

Two no-hint cases:
  native_adequate      native read is adequate -> chain resolves at native_http
  native_to_wigolo     native read is inadequate -> explicit wigolo_http step

Volatile fields (wall_ms, timestamps, request/invocation ids) are never
captured, so the snapshot is directly comparable between commits.

Usage::

    python tools/run_read_site_parity.py --output docs/research_quality/READ_SITE_PARITY.baseline.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

RUNTIME_TEST = REPO_ROOT / "tests" / "test_active_research_runtime.py"
SHORT_CHAR_THRESHOLD = 800
ADEQUATE = "z" * (SHORT_CHAR_THRESHOLD + 400)
WIGOLO_ADEQUATE = "y" * (SHORT_CHAR_THRESHOLD + 400)


def _load_test_module() -> Any:
    spec = importlib.util.spec_from_file_location("_art_parity", RUNTIME_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step_projection(step: Any) -> dict[str, Any]:
    if not isinstance(step, Mapping):
        return {}
    return {
        "backend": str(step.get("backend") or ""),
        "retrieval_state": str(step.get("retrieval_state") or ""),
        "attempted": bool(step.get("attempted")),
        "usable_content": bool(step.get("usable_content")),
        "adequacy_reason": str(step.get("adequacy_reason") or ""),
    }


def _source_projection(item: Mapping[str, Any]) -> dict[str, Any]:
    attempts = item.get("retrieval_attempts")
    return {
        "read_status": str(item.get("read_status") or ""),
        "final_backend": str(item.get("final_backend") or ""),
        "retrieval_attempts": [
            _step_projection(step) for step in (attempts or []) if isinstance(step, Mapping)
        ],
    }


def _capture(module: Any, *, case: str, read_gateway: Any, escalation: Any, tmp_dir: Path) -> dict:
    if case == "native_adequate":
        read_gateway = module._ShortNativeReadGateway(text=ADEQUATE)
    else:
        read_gateway = module._ShortNativeReadGateway(text="tiny")

    repository = module._TrackingRepository(module.RuntimeDatabase(tmp_dir / f"{case}.sqlite"))
    run = module._cutover_run(repository, f"run_parity_{case}")
    completed = module._cutover_service(
        repository,
        module._StructuredClient(),
        read_gateway=read_gateway,
        escalation_backend=escalation,
    ).execute(run.id, raise_on_error=True)

    metrics = completed.research_context.get(module.ACTIVE_RESEARCH_METRICS_KEY) or {}
    chain_rows = [
        {
            "action": str(row.get("action") or ""),
            "reason": str(row.get("reason") or ""),
            "attempted_backends": [
                str(item) for item in (row.get("attempted_backends") or [])
            ],
            "steps": [
                _step_projection(step)
                for step in (row.get("steps") or [])
                if isinstance(step, Mapping)
            ],
        }
        for row in (metrics.get("read_chain") or [])
        if isinstance(row, Mapping)
    ]
    reads = [
        {
            "candidate_id": str(item.get("candidate_id") or ""),
            "status": str(item.get("status") or ""),
            "content_chars": int(item.get("content_chars") or 0),
            "error_code": str(item.get("error_code") or ""),
            "backend": str(item.get("backend") or ""),
            "retrieval_state": str(item.get("retrieval_state") or ""),
        }
        for item in (metrics.get("reads") or [])
        if isinstance(item, Mapping)
    ]
    return {
        "case": case,
        "stop_reason": str(completed.stop_reason or ""),
        "provider_status": str(completed.provider_status or ""),
        "chain": chain_rows,
        "sources": [_source_projection(item) for item in (completed.selected_sources or [])],
        "reads": reads,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="")
    args = ap.parse_args(argv)

    os.environ.setdefault("RESEARCH_WIGOLO_ESCALATION", "http")
    os.environ.setdefault("WIGOLO_RERANKER", "off")

    import tempfile

    module = _load_test_module()
    tmp_dir = Path(tempfile.mkdtemp(prefix="read_site_parity_"))
    cases = {
        "native_adequate": _capture(
            module,
            case="native_adequate",
            read_gateway=None,
            escalation=module._CutoverEscalationBackend("y" * 9000),
            tmp_dir=tmp_dir,
        ),
        "native_to_wigolo": _capture(
            module,
            case="native_to_wigolo",
            read_gateway=None,
            escalation=module._CutoverEscalationBackend(WIGOLO_ADEQUATE),
            tmp_dir=tmp_dir,
        ),
    }

    import subprocess

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    ).stdout.strip()

    payload = {
        "schema": "read-site-parity-v1",
        "baseline_commit": commit,
        "fixture": "tests/test_active_research_runtime.py::_cutover_service",
        "normalization": {
            "captured": [
                "read outcomes (backend/content_chars/retrieval_state)",
                "terminal/chain action+reason",
                "backend_path (retrieval_attempts backends)",
                "record_outcome/step sequence",
                "source read_status/final_backend",
            ],
            "stripped_volatile": ["wall_ms", "timestamps", "request/invocation ids"],
        },
        "cases": cases,
    }

    if args.output:
        out = Path(args.output)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out} (commit {commit})")
    else:
        print(json.dumps(payload, indent=1, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
