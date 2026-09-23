"""§118 P2-A3-2c (v2): frozen-predecessor cohort runner.

Why v2 exists
-------------
v1 let the ambient production native reader re-derive each class's capability
demand from a loopback fixture, so BrowserBackend qualification was polluted by
unrelated native-reader behaviour. v2 supplies a **frozen predecessor** per
class (the pre-browser canonical state the A3-0 manifest pre-registered) and
still hands the decision to the **real** routing/eligibility/execution
primitives. It only fixes the *input premise* of routing.

Two legal consistency outcomes
------------------------------
1. ``PASS_ROUTE_DERIVED``      manifest demand == real ``route()`` demand
2. ``PASS_WITH_ROUTING_GAP``   the capability has **no** derivation path in A2,
   the demand was pre-registered before candidate evaluation, the class is
   explicitly qualification-only, real eligibility/execution is still used, and
   the gap is recorded. Exactly one class qualifies: ``document_heavy``.

Anything else fails closed.

``document_heavy`` single exception
-----------------------------------
A2 has no authoritative state that derives ``{pdf}``, so only the
``retrieval_state -> route() -> {pdf}`` step is skipped. Real
``backend_eligibility`` still decides which backend may run, and the real
executor still produces the outcome/provenance/budget.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.application.active_research_runtime import (  # noqa: E402
    NativeHttpBackendExecutor,
)
from src.web.research.browser_bakeoff import (  # noqa: E402
    BAKEOFF_CLASSES,
    BAKEOFF_UNIFIED_BUDGET,
    BROWSER_CHAIN_MAX_LENGTH,
    CLASS_ANTI_BOT,
    CLASS_CAPABILITY_DEMAND,
    CLASS_DOCUMENT_HEAVY,
    CLASS_JS_SHELL,
    CLASS_SESSION_REQUIRED,
    CLASS_SPA_DELAYED_RENDER,
    CLASS_STATIC_CONTROL,
    bakeoff_result_document,
    build_bakeoff_result,
    load_browser_bakeoff_manifest,
)
from src.web.research.chain_executor import (  # noqa: E402
    ChainStepResult,
    run_chain,
)
from src.web.research.crawl4ai_browser_executor import (  # noqa: E402
    ADVERTISED_CAPABILITIES,
    CRAWL4AI_BACKEND,
    Crawl4AIBridge,
    Crawl4AIBrowserBackendExecutor,
)
from src.web.research.progressive_routing import (  # noqa: E402
    BackendCapability,
    CAP_CONTENT_EXTRACTION,
    CAP_PLAIN_HTTP,
    EligibilityInputs,
    RoutingContext,
    backend_eligibility,
    route,
)
from src.web.research.read_adequacy import ADEQUATE_SHAPE  # noqa: E402
from src.web.research.read_escalation import (  # noqa: E402
    TIER_BROWSER,
    TIER_HTTP,
    charge_http_envelope,
    charge_run_envelope,
    reset_run_envelope,
    run_envelope_spent_ms,
)
from src.web.research.wigolo_backend import (  # noqa: E402
    TIER_HTTP as WIGOLO_TIER_HTTP,
    WigoloShadowReadBackend,
)
from src.web.research.wigolo_http_executor import WigoloHttpBackendExecutor  # noqa: E402

NATIVE = "native_http"
WIGOLO_HTTP = "wigolo_http"
BAKEOFF_CHAIN: tuple[str, ...] = (NATIVE, WIGOLO_HTTP, CRAWL4AI_BACKEND)

#: The frozen pre-browser state per class. Chosen so the *frozen* routing matrix
#: derives exactly the manifest's demand - nothing here names a backend.
PREDECESSOR_STATE: Mapping[str, str] = {
    CLASS_STATIC_CONTROL: "success",
    CLASS_JS_SHELL: "shell_page",
    CLASS_SPA_DELAYED_RENDER: "shell_page",
    CLASS_ANTI_BOT: "anti_bot",
    CLASS_SESSION_REQUIRED: "login_required",
    CLASS_DOCUMENT_HEAVY: "",  # no derivable state: see the single exception
}

#: The one class whose demand has no derivation path in A2.
QUALIFICATION_ONLY: frozenset[str] = frozenset({CLASS_DOCUMENT_HEAVY})
ROUTING_GAP = "A2_NO_PDF_DEMAND_DERIVATION"

DEFAULT_MANIFEST = (
    REPO_ROOT / "tests" / "fixtures" / "research_quality" / "browser_bakeoff_manifest.json"
)


def _backends() -> tuple[BackendCapability, ...]:
    return (
        BackendCapability(
            name=NATIVE, capabilities=frozenset({CAP_PLAIN_HTTP, CAP_CONTENT_EXTRACTION})
        ),
        BackendCapability(
            name=WIGOLO_HTTP,
            capabilities=frozenset({CAP_PLAIN_HTTP, CAP_CONTENT_EXTRACTION}),
        ),
        BackendCapability(
            name=CRAWL4AI_BACKEND, capabilities=frozenset(ADVERTISED_CAPABILITIES)
        ),
    )


def consistency_verdict(category: str) -> dict[str, Any]:
    """The two legal outcomes, evaluated against the REAL route()."""

    demand = frozenset(CLASS_CAPABILITY_DEMAND[category])
    state = PREDECESSOR_STATE.get(category, "")
    if state:
        decision = route(
            RoutingContext(
                candidate_id="consistency",
                current_backend=NATIVE,
                retrieval_state=state,
                attempted_backends=(NATIVE,),
                available_backends=BAKEOFF_CHAIN,
                host="x",
            )
        )
        derived = frozenset(decision.required_capabilities)
        if derived == demand:
            return {"verdict": "PASS_ROUTE_DERIVED", "derived": sorted(derived)}
        return {
            "verdict": "FAIL",
            "derived": sorted(derived),
            "reason": "manifest demand != route-derived demand",
        }
    # no derivable state: only legal for an explicitly qualification-only class
    if category in QUALIFICATION_ONLY:
        derivable = any(
            frozenset(caps) == demand
            for caps in (
                *(  # state map
                    v for v in __import__(
                        "src.web.research.progressive_routing",
                        fromlist=["STATE_CAPABILITY_REQUIREMENTS"],
                    ).STATE_CAPABILITY_REQUIREMENTS.values()
                ),
            )
        )
        if not derivable:
            return {
                "verdict": "PASS_WITH_ROUTING_GAP",
                "routing_gap": ROUTING_GAP,
                "qualification_only": True,
            }
    return {"verdict": "FAIL", "reason": "no legal consistency outcome"}


def _frozen_predecessor_executor(category: str) -> NativeHttpBackendExecutor:
    """A qualification-only predecessor: emits the frozen canonical state.

    It exists so the cohort tests the *contract* (given this premise, does the
    browser backend get scheduled and do its job) instead of testing how a real
    reader interprets a loopback fixture.
    """

    state = PREDECESSOR_STATE[category]

    def _read(url: str) -> Mapping[str, Any]:
        # shape the payload so classify() derives exactly the frozen state
        if state == "success":
            return {"ok": True, "url": url, "content": "x" * 1200, "title": "frozen ok"}
        if state == "shell_page":
            return {
                "ok": True,
                "url": url,
                "content": "Please enable JavaScript to continue.",
                "title": "frozen shell",
            }
        if state == "anti_bot":
            return {"ok": False, "url": url, "content": "", "error": "captcha detected"}
        if state == "login_required":
            return {
                "ok": False,
                "url": url,
                "content": "",
                "error": "login required to view",
            }
        return {"ok": False, "url": url, "content": "", "error": "unavailable"}

    return NativeHttpBackendExecutor(read_fn=_read)


def _slug(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "unknown").replace(".", "-")
    path = (parsed.path or "/").strip("/").replace("/", "-") or "root"
    return f"{host}-{path}"[:70]


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
        (s for s in results if s.usable_content and s.adequacy_reason == ADEQUATE_SHAPE),
        None,
    )
    if adequate is not None:
        return adequate
    return next((s for s in results if s.usable_content), results[-1])


def _executors(bridge: Crawl4AIBridge, *, category: str, session_id: str | None,
               mode: str, delay_ms: int) -> dict[str, Any]:
    max_chars = int(BAKEOFF_UNIFIED_BUDGET["max_chars"])
    return {
        NATIVE: _frozen_predecessor_executor(category),
        WIGOLO_HTTP: WigoloHttpBackendExecutor(
            backend=WigoloShadowReadBackend(tier=WIGOLO_TIER_HTTP, max_chars=max_chars),
            max_chars=max_chars,
            charge_envelope=charge_http_envelope,
        ),
        CRAWL4AI_BACKEND: Crawl4AIBrowserBackendExecutor(
            bridge=bridge,
            mode=mode,
            max_chars=max_chars,
            session_id=session_id,
            delay_ms=delay_ms,
            charge_envelope=lambda ms: charge_run_envelope(ms, TIER_BROWSER),
        ),
    }


def _row(
    *,
    fixture_id: str,
    category: str,
    chain_action: str,
    chain_reason: str,
    steps: Sequence[Any],
    recorded: Sequence[ChainStepResult],
    debit: float,
    cold: bool,
    consistency: Mapping[str, Any],
) -> dict[str, Any]:
    winner = _winner(recorded)
    browser_step = next((s for s in recorded if s.backend == CRAWL4AI_BACKEND), None)
    browser_called = any(s.backend == CRAWL4AI_BACKEND and s.attempted for s in steps)
    failure_reason = ""
    if winner is not None and not winner.usable_content:
        failure_reason = str(winner.adequacy_reason or winner.retrieval_state)
    elif winner is None:
        failure_reason = chain_reason
    return build_bakeoff_result(
        backend=CRAWL4AI_BACKEND,
        fixture_id=fixture_id,
        category=category,
        required_capabilities=sorted(CLASS_CAPABILITY_DEMAND[category]),
        browser_called=browser_called,
        browser_state=(browser_step.retrieval_state if browser_step else ""),
        browser_usable=bool(browser_step and browser_step.usable_content),
        outcome_state=(winner.retrieval_state if winner else "backend_failure"),
        usable_content=bool(winner and winner.retrieval_state == "success"),
        chain_action=chain_action,
        chain_reason=chain_reason,
        attempts=_attempt_rows(steps, recorded),
        wall_ms=sum(float((s.cost or {}).get("latency_ms") or 0.0) for s in recorded),
        fetch_ms=sum(float((s.cost or {}).get("fetch_ms") or 0.0) for s in recorded),
        cold=cold,
        bytes=int((winner.cost or {}).get("bytes") or 0) if winner else 0,
        content_type="",
        rendered=True if browser_step and browser_step.usable_content else None,
        cache_hit=False,
        failure_reason=failure_reason,
        provenance_complete=bool(
            chain_action and all(s.backend and s.retrieval_state for s in recorded)
        ),
        budget_respected=bool(
            debit <= BAKEOFF_UNIFIED_BUDGET["run_envelope_seconds"] * 1000.0 + 1.0
            and len(steps) <= BROWSER_CHAIN_MAX_LENGTH
        ),
    )


def _run_qualification_only(
    *,
    category: str,
    fixture_id: str,
    url: str,
    bridge: Crawl4AIBridge,
    cold: bool,
    session_id: str | None,
    mode: str,
    delay_ms: int,
) -> dict[str, Any]:
    """document_heavy: skip only the state->route->{pdf} step.

    Real ``backend_eligibility`` still decides which backend may run.
    """

    demand = frozenset(CLASS_CAPABILITY_DEMAND[category])
    registry = {b.name: b for b in _backends()}
    eligible: list[str] = []
    for backend in BAKEOFF_CHAIN:
        verdict = backend_eligibility(
            EligibilityInputs(
                backend=backend,
                required_capabilities=demand,
                attempted_backends=(),
                current_backend="",
                host=urlparse(url).hostname or "",
            ),
            backends=tuple(registry.values()),
        )
        if verdict.eligible:
            eligible.append(backend)
    executors = _executors(
        bridge, category=category, session_id=session_id, mode=mode, delay_ms=delay_ms
    )
    spent_before = run_envelope_spent_ms(TIER_BROWSER)
    recorded: list[ChainStepResult] = []
    steps: list[Any] = []
    chain_action = "exhaust"
    chain_reason = "no_capable_backend"
    if CRAWL4AI_BACKEND in eligible:
        from src.web.research.chain_executor import ChainAttemptRequest

        result = executors[CRAWL4AI_BACKEND].execute(
            ChainAttemptRequest(
                candidate_id=fixture_id,
                url=url,
                host=urlparse(url).hostname or "",
                backend=CRAWL4AI_BACKEND,
                chain_step=0,
                outer_attempt_number=1,
            )
        )
        if result.attempted:
            recorded.append(result)
        steps.append(
            __import__(
                "src.web.research.chain_executor", fromlist=["ChainStep"]
            ).ChainStep(
                chain_step=0,
                outer_attempt_number=1,
                backend=result.backend,
                retrieval_state=result.retrieval_state,
                attempted=bool(result.attempted),
                usable_content=bool(result.usable_content),
            )
        )
        chain_action = "resolve" if result.usable_content else "exhaust"
        chain_reason = "usable_content" if result.usable_content else "qualification_only"
    debit = max(0.0, run_envelope_spent_ms(TIER_BROWSER) - spent_before)
    return _row(
        fixture_id=fixture_id,
        category=category,
        chain_action=chain_action,
        chain_reason=chain_reason,
        steps=steps,
        recorded=recorded,
        debit=debit,
        cold=cold,
        consistency={"verdict": "PASS_WITH_ROUTING_GAP", "routing_gap": ROUTING_GAP},
    )


def run_cohort(*, python: str, manifest_path: Path, classes: Sequence[str] = ()) -> dict:
    if len(BAKEOFF_CHAIN) > BROWSER_CHAIN_MAX_LENGTH:
        raise SystemExit("bakeoff chain exceeds the frozen bound")
    manifest = load_browser_bakeoff_manifest(manifest_path)
    wanted = tuple(classes) or BAKEOFF_CLASSES

    print("consistency gate:", flush=True)
    verdicts: dict[str, Any] = {}
    for category in BAKEOFF_CLASSES:
        verdict = consistency_verdict(category)
        verdicts[category] = verdict
        print(f"  {category:22s} {verdict['verdict']} {verdict.get('routing_gap', '')}", flush=True)
    if any(v["verdict"] == "FAIL" for v in verdicts.values()):
        raise SystemExit("consistency gate failed closed")

    bridge = Crawl4AIBridge(python=python)
    bridge.start()
    print(f"worker READY startup_ms={bridge.startup_ms} "
          f"cancel_grace_ms={bridge.cancel_grace_ms}", flush=True)
    reset_run_envelope(TIER_HTTP)
    reset_run_envelope(TIER_BROWSER)

    rows: list[dict[str, Any]] = []
    first = True
    try:
        for entry in manifest["classes"]:
            category = entry["class"]
            if category not in wanted:
                continue
            mode = "pdf" if category == CLASS_DOCUMENT_HEAVY else "browser"
            session_id = f"cohort-{category}" if category == CLASS_SESSION_REQUIRED else None
            delay_ms = 1200 if category == CLASS_SPA_DELAYED_RENDER else 0
            for target in entry["targets"]:
                url = target["url"]
                fixture_id = f"{category}:{_slug(url)}"
                reset_run_envelope(TIER_BROWSER)
                if category in QUALIFICATION_ONLY:
                    measured = _run_qualification_only(
                        category=category, fixture_id=fixture_id, url=url,
                        bridge=bridge, cold=first, session_id=session_id,
                        mode=mode, delay_ms=delay_ms,
                    )
                else:
                    executors = _executors(
                        bridge, category=category, session_id=session_id,
                        mode=mode, delay_ms=delay_ms,
                    )
                    spent_before = run_envelope_spent_ms(TIER_BROWSER)
                    recorded: list[ChainStepResult] = []
                    chain = run_chain(
                        candidate_id=fixture_id, url=url,
                        host=urlparse(url).hostname or "",
                        outer_attempt_number=1, chain=BAKEOFF_CHAIN,
                        executors=executors, record_outcome=recorded.append,
                        attempted_backends=(), health_state_for=None,
                        backends=_backends(),
                    )
                    measured = _row(
                        fixture_id=fixture_id, category=category,
                        chain_action=chain.action, chain_reason=chain.reason,
                        steps=list(chain.steps), recorded=recorded,
                        debit=max(0.0, run_envelope_spent_ms(TIER_BROWSER) - spent_before),
                        cold=first, consistency=verdicts[category],
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
    document = bakeoff_result_document(rows, backend=CRAWL4AI_BACKEND)
    document["consistency"] = verdicts
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
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
