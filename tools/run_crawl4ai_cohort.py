"""§116 P2-A3-2c: run the frozen A3-0 six-class cohort against Crawl4AI.

Drives the real frozen ``chain_executor.run_chain`` with a bakeoff-local backend
registry in which ``crawl4ai`` advertises **only** ``js_render`` / ``pdf`` /
``session``. Production ``DEFAULT_BACKENDS`` and ``ACTIVE_READER_CHAIN`` are not
touched.

Per fixture:
  * ``document_heavy`` -> provider-native PDF execution strategy;
  * everything else    -> the browser path;
  * ``session_required`` -> a session id, so the worker's per-(session, mode)
    isolation is exercised.
The mode/session choice is execution configuration for a capability the fixture
already demands - not a second routing authority.

Usage::

    python tools/run_crawl4ai_cohort.py --python <isolated venv python> --output out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.web.research.browser_bakeoff import (  # noqa: E402
    BAKEOFF_CLASSES,
    BAKEOFF_UNIFIED_BUDGET,
    BROWSER_CHAIN_MAX_LENGTH,
    CLASS_CAPABILITY_DEMAND,
    CLASS_DOCUMENT_HEAVY,
    CLASS_SESSION_REQUIRED,
    bakeoff_result_document,
    build_bakeoff_result,
    load_browser_bakeoff_manifest,
)
from src.application.active_research_runtime import (  # noqa: E402
    NativeHttpBackendExecutor,
)
from src.web.research.chain_executor import ChainStepResult, run_chain  # noqa: E402
from src.web.research.wigolo_backend import (  # noqa: E402
    TIER_HTTP as _WIGOLO_TIER_HTTP,
    WigoloShadowReadBackend,
)
from src.web.research.wigolo_http_executor import (  # noqa: E402
    WigoloHttpBackendExecutor,
)
from src.web.research_gateway import ResearchWebGateway  # noqa: E402
from src.web.research.crawl4ai_browser_executor import (  # noqa: E402
    CRAWL4AI_BACKEND,
    ADVERTISED_CAPABILITIES,
    Crawl4AIBridge,
    Crawl4AIBrowserBackendExecutor,
)
from src.web.research.progressive_routing import (  # noqa: E402
    BackendCapability,
    CAP_CONTENT_EXTRACTION,
    CAP_PLAIN_HTTP,
)
from src.web.research.read_adequacy import ADEQUATE_SHAPE  # noqa: E402
from src.web.research.read_escalation import (  # noqa: E402
    charge_http_envelope,
    charge_run_envelope,
    run_envelope_spent_ms,
    reset_run_envelope,
    TIER_BROWSER,
    TIER_HTTP,
)

NATIVE = "native_http"
WIGOLO_HTTP = "wigolo_http"
BAKEOFF_CHAIN: tuple[str, ...] = (NATIVE, WIGOLO_HTTP, CRAWL4AI_BACKEND)

DEFAULT_MANIFEST = (
    REPO_ROOT / "tests" / "fixtures" / "research_quality" / "browser_bakeoff_manifest.json"
)


def _slug(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "unknown").replace(".", "-")
    path = (parsed.path or "/").strip("/").replace("/", "-") or "root"
    return f"{host}-{path}"[:70]


def _backends() -> tuple[BackendCapability, ...]:
    """Bakeoff-local registry: crawl4ai advertises only its real roles."""

    return (
        BackendCapability(
            name=NATIVE,
            capabilities=frozenset({CAP_PLAIN_HTTP, CAP_CONTENT_EXTRACTION}),
        ),
        BackendCapability(
            name=WIGOLO_HTTP,
            capabilities=frozenset({CAP_PLAIN_HTTP, CAP_CONTENT_EXTRACTION}),
        ),
        BackendCapability(
            name=CRAWL4AI_BACKEND,
            capabilities=frozenset(ADVERTISED_CAPABILITIES),
        ),
    )


def _attempt_rows(steps: Sequence[Any], results: Sequence[ChainStepResult]):
    pending: dict[str, list[ChainStepResult]] = {}
    for result in results:
        pending.setdefault(result.backend, []).append(result)
    rows = []
    for step in steps:
        queue = pending.get(step.backend) or []
        rows.append(queue.pop(0).to_dict() if step.attempted and queue else step.to_dict())
    return rows


def _winner(results: Sequence[ChainStepResult]) -> ChainStepResult | None:
    if not results:
        return None
    adequate = next(
        (
            s
            for s in results
            if s.usable_content and s.adequacy_reason == ADEQUATE_SHAPE
        ),
        None,
    )
    if adequate is not None:
        return adequate
    return next((s for s in results if s.usable_content), results[-1])


def _measure(
    *,
    fixture_id: str,
    category: str,
    url: str,
    bridge: Crawl4AIBridge,
    cold: bool,
    session_id: str | None,
    mode: str,
    delay_ms: int,
) -> dict[str, Any]:
    executor = Crawl4AIBrowserBackendExecutor(
        bridge=bridge,
        mode=mode,
        max_chars=int(BAKEOFF_UNIFIED_BUDGET["max_chars"]),
        session_id=session_id,
        delay_ms=delay_ms,
        charge_envelope=lambda ms: charge_run_envelope(ms, TIER_BROWSER),
    )
    gateway = ResearchWebGateway()
    executors = {
        NATIVE: NativeHttpBackendExecutor(
            read_fn=lambda url: gateway.read(
                url, max_chars=int(BAKEOFF_UNIFIED_BUDGET["max_chars"])
            )
        ),
        WIGOLO_HTTP: WigoloHttpBackendExecutor(
            backend=WigoloShadowReadBackend(
                tier=_WIGOLO_TIER_HTTP,
                max_chars=int(BAKEOFF_UNIFIED_BUDGET["max_chars"]),
            ),
            max_chars=int(BAKEOFF_UNIFIED_BUDGET["max_chars"]),
            charge_envelope=charge_http_envelope,
        ),
        CRAWL4AI_BACKEND: executor,
    }

    spent_before = run_envelope_spent_ms(TIER_BROWSER)
    recorded: list[ChainStepResult] = []
    chain = run_chain(
        candidate_id=fixture_id,
        url=url,
        host=urlparse(url).hostname or "",
        outer_attempt_number=1,
        chain=BAKEOFF_CHAIN,
        executors=executors,
        record_outcome=recorded.append,
        attempted_backends=(),
        health_state_for=None,
        backends=_backends(),
    )
    debit = max(0.0, run_envelope_spent_ms(TIER_BROWSER) - spent_before)
    steps = list(chain.steps)
    winner = _winner(recorded)
    browser_step = next(
        (s for s in recorded if s.backend == CRAWL4AI_BACKEND), None
    )
    browser_called = any(
        s.backend == CRAWL4AI_BACKEND and s.attempted for s in steps
    )
    wall_ms = sum(float((s.cost or {}).get("latency_ms") or 0.0) for s in recorded)
    fetch_ms = sum(float((s.cost or {}).get("fetch_ms") or 0.0) for s in recorded)
    failure_reason = ""
    if winner is not None and not winner.usable_content:
        failure_reason = str(winner.adequacy_reason or winner.retrieval_state)
    elif winner is None:
        failure_reason = chain.reason

    return build_bakeoff_result(
        backend=CRAWL4AI_BACKEND,
        fixture_id=fixture_id,
        category=category,
        required_capabilities=sorted(CLASS_CAPABILITY_DEMAND[category]),
        browser_called=browser_called,
        browser_state=(browser_step.retrieval_state if browser_step else ""),
        browser_usable=bool(browser_step and browser_step.usable_content),
        # a chain that never produced content is a canonical failure, never
        # the routing action ("exhaust" is not a retrieval state)
        outcome_state=(winner.retrieval_state if winner else "backend_failure"),
        # the frozen validator defines usable_content as "the outcome was a
        # success"; content-obtained-but-inadequate is carried by
        # browser_state / browser_usable and the attempts list instead.
        usable_content=bool(winner and winner.retrieval_state == "success"),
        chain_action=chain.action,
        chain_reason=chain.reason,
        attempts=_attempt_rows(steps, recorded),
        wall_ms=wall_ms,
        fetch_ms=fetch_ms,
        cold=cold,
        bytes=int((winner.cost or {}).get("bytes") or 0) if winner else 0,
        content_type="",
        rendered=True if browser_step and browser_step.usable_content else None,
        cache_hit=False,
        failure_reason=failure_reason,
        provenance_complete=bool(
            chain.action and all(s.backend and s.retrieval_state for s in recorded)
        ),
        budget_respected=bool(
            debit <= BAKEOFF_UNIFIED_BUDGET["run_envelope_seconds"] * 1000.0 + 1.0
            and len(steps) <= BROWSER_CHAIN_MAX_LENGTH
        ),
    )


def run_cohort(*, python: str, manifest_path: Path, classes: Sequence[str] = ()) -> dict:
    if len(BAKEOFF_CHAIN) > BROWSER_CHAIN_MAX_LENGTH:
        raise SystemExit("bakeoff chain exceeds the frozen bound")
    manifest = load_browser_bakeoff_manifest(manifest_path)
    wanted = tuple(classes) or BAKEOFF_CLASSES

    bridge = Crawl4AIBridge(python=python)
    bridge.start()
    print(f"worker READY startup_ms={bridge.startup_ms} "
          f"cancel_grace_ms={bridge.cancel_grace_ms}", flush=True)

    reset_run_envelope(TIER_HTTP)
    reset_run_envelope(TIER_BROWSER)

    rows: list[dict[str, Any]] = []
    first = True
    try:
        for row in manifest["classes"]:
            category = row["class"]
            if category not in wanted:
                continue
            mode = "pdf" if category == CLASS_DOCUMENT_HEAVY else "browser"
            session_id = f"cohort-{category}" if category == CLASS_SESSION_REQUIRED else None
            delay_ms = 1200 if category == "spa_delayed_render" else 0
            for target in row["targets"]:
                url = target["url"]
                fixture_id = f"{category}:{_slug(url)}"
                reset_run_envelope(TIER_BROWSER)
                measured = _measure(
                    fixture_id=fixture_id,
                    category=category,
                    url=url,
                    bridge=bridge,
                    cold=first,
                    session_id=session_id,
                    mode=mode,
                    delay_ms=delay_ms,
                )
                first = False
                rows.append(measured)
                print(
                    f"{category:20s} browser_called={str(measured['browser_called']):5s} "
                    f"bstate={measured['browser_state']:16s} usable={measured['usable_content']} "
                    f"wall={measured['wall_ms']:8.1f}ms chain={measured['chain_action']}",
                    flush=True,
                )
    finally:
        bridge.stop()
    return bakeoff_result_document(rows, backend=CRAWL4AI_BACKEND)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, help="isolated venv interpreter")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--class", dest="classes", action="append", default=[])
    args = parser.parse_args(argv)

    document = run_cohort(
        python=args.python, manifest_path=args.manifest, classes=args.classes
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output} ({len(document['results'])} rows)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
