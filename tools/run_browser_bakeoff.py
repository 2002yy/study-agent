"""§110 P2-A3-1 browser bakeoff harness (one side at a time).

Runs the frozen A3-0 fixture manifest through a **bakeoff-local** reader chain::

    native_http -> wigolo_http -> <candidate browser backend>

and writes one ``browser-bakeoff-result-v1`` artifact per backend. The chain is
built here and handed to the frozen ``chain_executor.run_chain``; the Study Agent
production runtime is not involved and ``ACTIVE_READER_CHAIN`` is not modified.

This is a measurement instrument, not a production path. It grants no authority:
no evidence, support or Gate is written.

Usage::

    python tools/run_browser_bakeoff.py --backend wigolo_browser --output out.json
    python tools/run_browser_bakeoff.py --backend wigolo_browser --class js_shell
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
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
    CANDIDATE_BACKENDS,
    CLASS_CAPABILITY_DEMAND,
    bakeoff_result_document,
    build_bakeoff_result,
    load_browser_bakeoff_manifest,
)
from src.web.research.chain_executor import ChainStepResult, run_chain  # noqa: E402
from src.web.research.read_adequacy import ADEQUATE_SHAPE  # noqa: E402
from src.web.research.read_escalation import (  # noqa: E402
    charge_http_envelope,
    http_envelope_spent_ms,
    reset_http_envelope,
)
from src.web.research.wigolo_backend import (  # noqa: E402
    TIER_BROWSER,
    TIER_HTTP,
    WigoloShadowReadBackend,
)
from src.web.research.wigolo_browser_executor import (  # noqa: E402
    WIGOLO_BROWSER_BACKEND,
    WigoloBrowserBackendExecutor,
)
from src.web.research.wigolo_http_executor import (  # noqa: E402
    WIGOLO_HTTP_BACKEND,
    WigoloHttpBackendExecutor,
)
from src.web.research_gateway import ResearchWebGateway  # noqa: E402

NATIVE_HTTP_BACKEND = "native_http"

#: The bakeoff chain. Length is asserted against the frozen bound below.
BAKEOFF_CHAIN: tuple[str, ...] = (
    NATIVE_HTTP_BACKEND,
    WIGOLO_HTTP_BACKEND,
    WIGOLO_BROWSER_BACKEND,
)

DEFAULT_MANIFEST = (
    REPO_ROOT / "tests" / "fixtures" / "research_quality" / "browser_bakeoff_manifest.json"
)


def _slug(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "unknown").replace(".", "-")
    path = (parsed.path or "/").strip("/").replace("/", "-") or "root"
    return f"{host}-{path}"[:80]


def _executors(*, max_chars: int, base_url: str, timeout: float) -> dict[str, Any]:
    gateway = ResearchWebGateway()

    def _native(url: str) -> Mapping[str, Any]:
        return gateway.read(url, max_chars=max_chars)

    http_backend = WigoloShadowReadBackend(
        base_url=base_url, tier=TIER_HTTP, max_chars=max_chars, timeout_seconds=timeout
    )
    browser_backend = WigoloShadowReadBackend(
        base_url=base_url, tier=TIER_BROWSER, max_chars=max_chars, timeout_seconds=timeout
    )
    return {
        NATIVE_HTTP_BACKEND: NativeHttpBackendExecutor(read_fn=_native),
        WIGOLO_HTTP_BACKEND: WigoloHttpBackendExecutor(
            backend=http_backend,
            max_chars=max_chars,
            charge_envelope=charge_http_envelope,
        ),
        WIGOLO_BROWSER_BACKEND: WigoloBrowserBackendExecutor(
            backend=browser_backend,
            max_chars=max_chars,
            charge_envelope=charge_http_envelope,
        ),
    }


def _attempted(steps: Sequence[ChainStepResult]) -> list[ChainStepResult]:
    return [step for step in steps if step.attempted]


def _winner(steps: Sequence[ChainStepResult]) -> ChainStepResult | None:
    attempted = _attempted(steps)
    if not attempted:
        return None
    adequate = next(
        (
            step
            for step in attempted
            if step.usable_content and step.adequacy_reason == ADEQUATE_SHAPE
        ),
        None,
    )
    if adequate is not None:
        return adequate
    return next((step for step in attempted if step.usable_content), attempted[-1])


def _failure_reason(steps: Sequence[ChainStepResult], chain_reason: str) -> str:
    for step in _attempted(steps):
        if step.usable_content:
            continue
        cost = step.cost if isinstance(step.cost, Mapping) else {}
        return str(
            cost.get("honesty_downgrade")
            or step.adequacy_reason
            or cost.get("error")
            or cost.get("raw_state")
            or step.retrieval_state
        )
    return "" if any(step.usable_content for step in _attempted(steps)) else chain_reason


def _attempt_rows(
    steps: Sequence[Any], results: Sequence[ChainStepResult]
) -> list[dict[str, Any]]:
    """Chain-ordered attempt rows, with cost for every real attempt.

    ``ChainStep`` (the chain's own record) has no cost, and ``ChainStepResult``
    (the executor's report) has no policy-skipped steps. The artifact needs
    both, so they are merged by order.
    """

    pending: dict[str, list[ChainStepResult]] = {}
    for result in results:
        pending.setdefault(result.backend, []).append(result)
    rows: list[dict[str, Any]] = []
    for step in steps:
        queue = pending.get(step.backend) or []
        if step.attempted and queue:
            rows.append(queue.pop(0).to_dict())
        else:
            rows.append(step.to_dict())
    return rows


def measure_fixture(
    *,
    backend: str,
    fixture_id: str,
    category: str,
    url: str,
    executors: Mapping[str, Any],
    cold: bool,
) -> dict[str, Any]:
    """One (backend, fixture) row, measured through the frozen chain executor."""

    spent_before = http_envelope_spent_ms()
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
    )
    spent_after = http_envelope_spent_ms()

    steps = list(chain.steps)
    # ``recorded`` holds one ChainStepResult per *real* attempt (with cost and
    # adequacy); ``steps`` holds every step the chain took, policy skips
    # included. Both are kept: the first drives the verdict, the second is the
    # audit record.
    results = list(recorded)
    winner = _winner(results)
    attempted = results
    browser_steps = [
        step for step in attempted if step.backend == backend
    ]
    browser_step = browser_steps[-1] if browser_steps else None
    browser_called = any(
        step.backend == backend and step.attempted for step in steps
    )
    wall_ms = sum(float((step.cost or {}).get("latency_ms") or 0.0) for step in attempted)
    fetch_ms = sum(float((step.cost or {}).get("fetch_ms") or 0.0) for step in attempted)
    debit = max(0.0, spent_after - spent_before)
    budget_respected = bool(
        debit <= BAKEOFF_UNIFIED_BUDGET["run_envelope_seconds"] * 1000.0 + 1.0
        and len(steps) <= BROWSER_CHAIN_MAX_LENGTH
    )
    provenance_complete = bool(
        chain.action
        and all(step.backend and step.retrieval_state for step in attempted)
        and (winner is None or winner.usable_content or bool(winner.retrieval_state))
    )
    return build_bakeoff_result(
        backend=backend,
        fixture_id=fixture_id,
        category=category,
        required_capabilities=sorted(CLASS_CAPABILITY_DEMAND[category]),
        browser_called=browser_called,
        browser_state=(browser_step.retrieval_state if browser_step else ""),
        browser_usable=bool(browser_step and browser_step.usable_content),
        outcome_state=(winner.retrieval_state if winner else chain.action),
        usable_content=bool(winner and winner.usable_content),
        chain_action=chain.action,
        chain_reason=chain.reason,
        attempts=_attempt_rows(steps, results),
        wall_ms=wall_ms,
        fetch_ms=fetch_ms,
        cold=cold,
        bytes=int((winner.cost or {}).get("bytes") or 0) if winner else 0,
        content_type=str((winner.cost or {}).get("content_type") or "") if winner else "",
        rendered=(winner.cost or {}).get("rendered") if winner else None,
        cache_hit=(winner.cost or {}).get("cache_hit") if winner else None,
        failure_reason=_failure_reason(results, chain.reason),
        provenance_complete=provenance_complete,
        budget_respected=budget_respected,
    )


def run_bakeoff(
    *,
    backend: str,
    manifest_path: Path,
    base_url: str,
    timeout: float,
    classes: Iterable[str] = (),
) -> dict[str, Any]:
    if backend not in CANDIDATE_BACKENDS:
        raise SystemExit(f"backend must be one of {CANDIDATE_BACKENDS!r}")
    if backend != WIGOLO_BROWSER_BACKEND:
        raise SystemExit(
            f"{backend!r} adapter is not implemented yet (P2-A3-2); "
            f"this harness only measures {WIGOLO_BROWSER_BACKEND!r}"
        )
    if len(BAKEOFF_CHAIN) > BROWSER_CHAIN_MAX_LENGTH:
        raise SystemExit("the bakeoff chain exceeds the frozen bound")

    manifest = load_browser_bakeoff_manifest(manifest_path)
    wanted = tuple(classes) or BAKEOFF_CLASSES
    max_chars = int(BAKEOFF_UNIFIED_BUDGET["max_chars"])

    # One envelope for the whole bakeoff run, exactly like production.
    reset_http_envelope()
    executors = _executors(max_chars=max_chars, base_url=base_url, timeout=timeout)

    rows: list[dict[str, Any]] = []
    first = True
    for row in manifest["classes"]:
        category = row["class"]
        if category not in wanted:
            continue
        for target in row["targets"]:
            url = target["url"]
            fixture_id = f"{category}:{_slug(url)}"
            # One fixture is one bounded measurement unit: each starts from the
            # frozen envelope, otherwise the first expensive page would starve
            # every later one and the comparison would measure order, not
            # backends. The *production* per-run sharing of this envelope across
            # the http and browser tiers is reported separately (see §110).
            reset_http_envelope()
            measured = measure_fixture(
                backend=backend,
                fixture_id=fixture_id,
                category=category,
                url=url,
                executors=executors,
                cold=first,
            )
            first = False
            rows.append(measured)
            print(
                f"{category:20s} browser_called={str(measured['browser_called']):5s} "
                f"state={measured['outcome_state']:16s} usable={measured['usable_content']} "
                f"wall={measured['wall_ms']:8.1f}ms"
            )
    return bakeoff_result_document(rows, backend=backend)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default=WIGOLO_BROWSER_BACKEND)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:3333")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--class", dest="classes", action="append", default=[])
    args = parser.parse_args(argv)

    document = run_bakeoff(
        backend=args.backend,
        manifest_path=args.manifest,
        base_url=args.base_url,
        timeout=args.timeout,
        classes=args.classes,
    )
    document["measured_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output} ({len(document['results'])} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
