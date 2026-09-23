"""§108 P2-A3-0 browser-backend bakeoff contract (production-inert).

A3 answers exactly one question:

    When A2 routing has already decided that a plain reader cannot settle a
    candidate, which ``BrowserBackend`` is the better production rendered reader?

Two candidates compete: ``wigolo_browser`` (already modelled as a capability in
the routing registry) and ``crawl4ai`` (not installed, not registered).

Why a contract comes first
--------------------------

The risk in A3 is not architecture. It is letting a browser become a universal
fallback: ``native -> wigolo_http -> browser_A -> browser_B`` is one small step
away from turning the bounded chain back into a long tail. A comparison that is
run before its success definition exists becomes "whichever felt better".

So this module freezes, *before either adapter is written*:

* the six fixture classes and the capability each one demands,
* the routing decision that must precede a browser call in each class,
* the static-control guard (a browser must not start when routing did not ask),
* one shared budget for both candidates,
* the comparison dimensions and their direction,
* the provenance an attempt must carry,
* the winner criteria, including disqualifiers,
* the A2 surface A3 may not modify.

Scope
-----

Nothing in the runtime, the adapter, the chain executor, the router or candidate
resolution imports this module. It registers no backend and changes no chain. It
is a frozen contract plus a fail-closed validator for its manifest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.web.research.failure_taxonomy import RETRIEVAL_STATES
from src.web.research.progressive_routing import (
    ACTION_BLOCK_RUN,
    ACTION_DEFER,
    ACTION_EXHAUST,
    ACTION_RESOLVE,
    ACTION_TRY_BACKEND,
    CAP_ANTI_BOT_RECOVERY,
    CAP_CONTENT_EXTRACTION,
    CAP_JS_RENDER,
    CAP_PDF,
    CAP_PLAIN_HTTP,
    CAP_SESSION,
)
from src.web.research.read_escalation import (
    EFFECTIVE_TIMEOUT_FLOOR_SECONDS,
    HTTP_MIN_HARD_SECONDS_DEFAULT,
    HTTP_RUN_ENVELOPE_DEFAULT,
)
from src.web.research.wigolo_backend import WIGOLO_FETCH_MAX_CHARS

SCHEMA_VERSION = "browser-bakeoff-manifest-v1"
BAKEOFF_VERSION = "a3-0"

# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

#: The two backends under comparison. ``crawl4ai`` is intentionally **not**
#: installed and **not** registered while the contract is being frozen.
CANDIDATE_BACKENDS: tuple[str, ...] = ("wigolo_browser", "crawl4ai")

#: The production reader chain at A3-0. A3-0 must not alter it; the browser
#: backend enters the chain only after A3-3 picks a winner.
PRODUCTION_CHAIN_AT_A3_0: tuple[str, ...] = ("native_http", "wigolo_http")

#: ``native -> alternate http -> one browser``. A chain longer than this would
#: recreate the long tail this contract exists to prevent.
BROWSER_CHAIN_MAX_LENGTH = 3

# ---------------------------------------------------------------------------
# Fixture classes
# ---------------------------------------------------------------------------

CLASS_STATIC_CONTROL = "static_control"
CLASS_JS_SHELL = "js_shell"
CLASS_SPA_DELAYED_RENDER = "spa_delayed_render"
CLASS_ANTI_BOT = "anti_bot"
CLASS_SESSION_REQUIRED = "session_required"
CLASS_DOCUMENT_HEAVY = "document_heavy"

BAKEOFF_CLASSES: tuple[str, ...] = (
    CLASS_STATIC_CONTROL,
    CLASS_JS_SHELL,
    CLASS_SPA_DELAYED_RENDER,
    CLASS_ANTI_BOT,
    CLASS_SESSION_REQUIRED,
    CLASS_DOCUMENT_HEAVY,
)

#: Capability each class demands from the *next* backend. These are exactly the
#: frozen routing capabilities - A3 invents no new capability word.
CLASS_CAPABILITY_DEMAND: Mapping[str, frozenset[str]] = {
    CLASS_STATIC_CONTROL: frozenset(),
    CLASS_JS_SHELL: frozenset({CAP_JS_RENDER}),
    CLASS_SPA_DELAYED_RENDER: frozenset({CAP_JS_RENDER}),
    CLASS_ANTI_BOT: frozenset({CAP_ANTI_BOT_RECOVERY}),
    CLASS_SESSION_REQUIRED: frozenset({CAP_SESSION}),
    CLASS_DOCUMENT_HEAVY: frozenset({CAP_PDF}),
}

#: The A2 routing action that must precede any browser call in this class.
#: ``static_control`` must be settled by the plain chain (``resolve``); the
#: others legitimately route onward (``try_backend``).
CLASS_EXPECTED_ROUTING: Mapping[str, str] = {
    CLASS_STATIC_CONTROL: ACTION_RESOLVE,
    CLASS_JS_SHELL: ACTION_TRY_BACKEND,
    CLASS_SPA_DELAYED_RENDER: ACTION_TRY_BACKEND,
    CLASS_ANTI_BOT: ACTION_TRY_BACKEND,
    CLASS_SESSION_REQUIRED: ACTION_TRY_BACKEND,
    CLASS_DOCUMENT_HEAVY: ACTION_TRY_BACKEND,
}

#: The static-control guard: the browser must **not** be started for a page the
#: plain chain can already read. Proving rescue is not enough - a production
#: browser backend must also prove it stays out of the way.
CLASS_EXPECTS_BROWSER_CALL: Mapping[str, bool] = {
    CLASS_STATIC_CONTROL: False,
    CLASS_JS_SHELL: True,
    CLASS_SPA_DELAYED_RENDER: True,
    CLASS_ANTI_BOT: True,
    CLASS_SESSION_REQUIRED: True,
    CLASS_DOCUMENT_HEAVY: True,
}

#: Machine-checkable success per class. ``browser_invocation`` is one of
#: ``forbidden`` / ``required_once``. ``usable_content_required`` is False only
#: where an honest canonical failure is an acceptable outcome.
CLASS_SUCCESS_DEFINITION: Mapping[str, Mapping[str, Any]] = {
    CLASS_STATIC_CONTROL: {
        "browser_invocation": "forbidden",
        "usable_content_required": True,
        "canonical_state_required": True,
        "notes": "The plain chain must settle it; starting a browser is a failure.",
    },
    CLASS_JS_SHELL: {
        "browser_invocation": "required_once",
        "usable_content_required": True,
        "canonical_state_required": True,
        "notes": "The shell must be replaced by rendered content.",
    },
    CLASS_SPA_DELAYED_RENDER: {
        "browser_invocation": "required_once",
        "usable_content_required": True,
        "canonical_state_required": True,
        "notes": "Content appears only after deferred client-side work.",
    },
    CLASS_ANTI_BOT: {
        "browser_invocation": "required_once",
        "usable_content_required": True,
        "canonical_state_required": True,
        "notes": "Recovery is the point of the class; a denial is a miss.",
    },
    CLASS_SESSION_REQUIRED: {
        "browser_invocation": "required_once",
        "usable_content_required": False,
        "canonical_state_required": True,
        "notes": (
            "Honest ``login_required`` is acceptable; silently returning the "
            "login page as content is not."
        ),
    },
    CLASS_DOCUMENT_HEAVY: {
        "browser_invocation": "required_once",
        "usable_content_required": True,
        "canonical_state_required": True,
        "notes": "Document bytes must reach the extractor, not an HTML wrapper.",
    },
}

# ---------------------------------------------------------------------------
# One shared budget
# ---------------------------------------------------------------------------

#: Both candidates run under *the same* numbers. These reuse the frozen A2
#: constants rather than restating literals, so a bakeoff can never hand one
#: side a larger budget than the other - or than production.
BAKEOFF_UNIFIED_BUDGET: Mapping[str, Any] = {
    "min_hard_seconds_left": HTTP_MIN_HARD_SECONDS_DEFAULT,
    "run_envelope_seconds": HTTP_RUN_ENVELOPE_DEFAULT,
    "effective_timeout_floor_seconds": EFFECTIVE_TIMEOUT_FLOOR_SECONDS,
    "max_chars": WIGOLO_FETCH_MAX_CHARS,
    # Bakeoff-only parameter: identical for both candidates, not a production
    # policy, and superseded by whatever A3-3 records as the winner's envelope.
    "per_page_timeout_seconds": 20.0,
}

# ---------------------------------------------------------------------------
# Comparison dimensions
# ---------------------------------------------------------------------------

#: ``direction`` is ``higher_better`` / ``lower_better`` / ``required``.
BAKEOFF_DIMENSIONS: tuple[Mapping[str, str], ...] = (
    {"key": "js_render_success", "direction": "higher_better", "unit": "rate"},
    {"key": "shell_rescue", "direction": "higher_better", "unit": "rate"},
    {"key": "anti_bot_recovery", "direction": "higher_better", "unit": "rate"},
    {"key": "session_capability", "direction": "required", "unit": "bool"},
    {"key": "document_support", "direction": "required", "unit": "bool"},
    {"key": "latency_warm_ms", "direction": "lower_better", "unit": "ms"},
    {"key": "cold_start_ms", "direction": "lower_better", "unit": "ms"},
    {"key": "resident_memory_delta_mb", "direction": "lower_better", "unit": "mb"},
    {"key": "daemon_restarts", "direction": "lower_better", "unit": "count"},
    {"key": "failure_transparency", "direction": "required", "unit": "rate"},
    {"key": "provenance_completeness", "direction": "required", "unit": "rate"},
    {"key": "budget_boundedness", "direction": "required", "unit": "bool"},
    {"key": "static_control_silence", "direction": "required", "unit": "bool"},
    {"key": "integration_complexity", "direction": "lower_better", "unit": "score"},
    {"key": "maintenance_burden", "direction": "lower_better", "unit": "score"},
)

#: Dimensions that must be *perfect* before any rate comparison is meaningful.
REQUIRED_DIMENSIONS: tuple[str, ...] = (
    "session_capability",
    "document_support",
    "failure_transparency",
    "provenance_completeness",
    "budget_boundedness",
    "static_control_silence",
)

#: Every attempt must be able to answer these. They are the A2 artifacts the
#: bakeoff is required to keep populated, not a new ledger.
PROVENANCE_REQUIREMENTS: tuple[str, ...] = (
    "runtime_read_outcome",
    "read_timing",
    "read_chain",
    "source_retrieval_attempts",
    "final_backend",
    "failure_attempt_id",
)

# ---------------------------------------------------------------------------
# Winner criteria (pre-registered)
# ---------------------------------------------------------------------------

WINNER_CRITERIA: Mapping[str, Any] = {
    # Any of these removes a candidate from consideration outright.
    "disqualifiers": (
        "browser_started_on_static_control",
        "budget_exceeded",
        "missing_canonical_retrieval_state",
        "provenance_incomplete",
        "requires_core_semantics_change",
        "chain_longer_than_max",
    ),
    "required_dimensions": REQUIRED_DIMENSIONS,
    "decision_rules": {
        "wigolo_browser_wins": (
            "no disqualifier; all required dimensions met; better on the "
            "majority of rate/latency dimensions"
        ),
        "crawl4ai_wins": (
            "no disqualifier; all required dimensions met; better on the "
            "majority of rate/latency dimensions and more transparent failures"
        ),
        "complementary": (
            "both survive, neither dominates. Production keeps exactly ONE "
            "primary BrowserBackend; a second may exist only as a "
            "capability-bounded special fallback and must not extend the chain "
            "beyond BROWSER_CHAIN_MAX_LENGTH"
        ),
    },
    "default_goal": "one primary BrowserBackend",
    "tie_break": (
        "prefer the candidate with better failure transparency and provenance; "
        "if still tied, prefer the lower maintenance burden; if still tied, "
        "prefer the one already reachable through the existing daemon "
        "(wigolo_browser), because integration complexity is a standing cost"
    ),
}

# ---------------------------------------------------------------------------
# Hard boundary: what A3 may not touch
# ---------------------------------------------------------------------------

#: A browser backend may only register a capability and implement a
#: ``BackendExecutor``. Needing to change any of these means the adapter design
#: is wrong, not that the core should move.
FORBIDDEN_CORE_CHANGES: tuple[str, ...] = (
    "candidate_resolution.resolve_candidate",
    "candidate_resolution.RESOLUTION_STATES",
    "progressive_routing.route",
    "progressive_routing.schedulable_now",
    "progressive_routing.backend_eligibility",
    "progressive_routing.ACTION_*",
    "chain_executor.run_chain",
    "failure_taxonomy.RETRIEVAL_STATES",
    "failure_taxonomy.classify",
)

#: Actions a browser backend *may* take.
ALLOWED_ADAPTER_SURFACE: tuple[str, ...] = (
    "register_BackendCapability",
    "implement_BackendExecutor",
    "join_existing_chain",
)

ROUTING_ACTIONS: frozenset[str] = frozenset(
    {
        ACTION_RESOLVE,
        ACTION_TRY_BACKEND,
        ACTION_DEFER,
        ACTION_BLOCK_RUN,
        ACTION_EXHAUST,
    }
)

FROZEN_CAPABILITIES: frozenset[str] = frozenset(
    {
        CAP_PLAIN_HTTP,
        CAP_CONTENT_EXTRACTION,
        CAP_JS_RENDER,
        CAP_SESSION,
        CAP_ANTI_BOT_RECOVERY,
        CAP_PDF,
    }
)

TARGET_KINDS: frozenset[str] = frozenset({"public_url", "synthetic_local"})


class BrowserBakeoffContractError(ValueError):
    """A manifest or result that violates the frozen A3 contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BrowserBakeoffContractError(message)


def validate_browser_bakeoff_manifest(payload: Mapping[str, Any]) -> None:
    """Fail-closed validation of one bakeoff manifest.

    Every failure raises :class:`BrowserBakeoffContractError`; a manifest is
    never partially accepted.
    """

    _require(isinstance(payload, Mapping), "manifest must be a mapping")
    _require(
        payload.get("schema_version") == SCHEMA_VERSION,
        f"schema_version must be {SCHEMA_VERSION!r}",
    )
    _require(
        tuple(payload.get("candidate_backends") or ()) == CANDIDATE_BACKENDS,
        f"candidate_backends must be {CANDIDATE_BACKENDS!r}",
    )
    _require(
        dict(payload.get("budget") or {}) == dict(BAKEOFF_UNIFIED_BUDGET),
        "budget must equal the unified bakeoff budget exactly",
    )
    _require(
        tuple(payload.get("provenance_requirements") or ()) == PROVENANCE_REQUIREMENTS,
        "provenance_requirements must equal the frozen requirement list",
    )

    classes = payload.get("classes")
    _require(
        isinstance(classes, list) and bool(classes),
        "classes must be a non-empty list",
    )
    rows = list(classes or [])
    seen_classes: list[str] = []
    seen_urls: list[str] = []
    for row in rows:
        _require(isinstance(row, Mapping), "every class row must be a mapping")
        name = str(row.get("class") or "")
        _require(name in BAKEOFF_CLASSES, f"unknown fixture class: {name!r}")
        seen_classes.append(name)

        demand = frozenset(row.get("capability_demand") or ())
        _require(
            demand <= FROZEN_CAPABILITIES,
            f"{name}: capability_demand leaves the frozen vocabulary",
        )
        _require(
            demand == CLASS_CAPABILITY_DEMAND[name],
            f"{name}: capability_demand must equal the contract",
        )
        routing = str(row.get("expected_routing") or "")
        _require(
            routing in ROUTING_ACTIONS,
            f"{name}: expected_routing {routing!r} is not a routing action",
        )
        _require(
            routing == CLASS_EXPECTED_ROUTING[name],
            f"{name}: expected_routing must equal the contract",
        )
        _require(
            bool(row.get("expect_browser_call")) is CLASS_EXPECTS_BROWSER_CALL[name],
            f"{name}: expect_browser_call must equal the contract",
        )
        if name == CLASS_STATIC_CONTROL:
            # The guard is restated as its own assertion so a manifest can never
            # quietly opt the control into a browser call.
            _require(
                row.get("expect_browser_call") is False,
                "static_control must never start a browser",
            )
        _require(
            dict(row.get("success_definition") or {})
            == dict(CLASS_SUCCESS_DEFINITION[name]),
            f"{name}: success_definition must equal the contract",
        )

        targets = row.get("targets")
        _require(
            isinstance(targets, list) and bool(targets),
            f"{name}: at least one target is required",
        )
        for target in list(targets or []):
            _require(isinstance(target, Mapping), f"{name}: target must be a mapping")
            url = str(target.get("url") or "")
            _require(url.startswith(("http://", "https://")), f"{name}: bad url {url!r}")
            kind = str(target.get("kind") or "")
            _require(
                kind in TARGET_KINDS, f"{name}: target kind {kind!r} is not allowed"
            )
            seen_urls.append(url)

    _require(
        tuple(seen_classes) == BAKEOFF_CLASSES,
        "classes must appear exactly once each, in the frozen order",
    )
    _require(
        len(seen_urls) == len(set(seen_urls)), "target urls must be unique"
    )


def load_browser_bakeoff_manifest(path: str | Path) -> dict[str, Any]:
    """Load and validate a bakeoff manifest (fail-closed)."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_browser_bakeoff_manifest(payload)
    return payload


def intended_browser_chain(winner: str) -> tuple[str, ...]:
    """The chain a winning backend would join - never longer than the bound."""

    _require(
        winner in CANDIDATE_BACKENDS,
        f"winner must be one of {CANDIDATE_BACKENDS!r}",
    )
    chain = (*PRODUCTION_CHAIN_AT_A3_0, winner)
    _require(
        len(chain) <= BROWSER_CHAIN_MAX_LENGTH,
        "the browser chain must not exceed BROWSER_CHAIN_MAX_LENGTH",
    )
    _require(len(set(chain)) == len(chain), "the browser chain must not repeat a backend")
    return chain


def dimension_keys() -> tuple[str, ...]:
    return tuple(str(item["key"]) for item in BAKEOFF_DIMENSIONS)


def required_dimension_keys() -> tuple[str, ...]:
    return REQUIRED_DIMENSIONS


# ---------------------------------------------------------------------------
# §110 P2-A3-1: the bakeoff result artifact
# ---------------------------------------------------------------------------

RESULT_SCHEMA_VERSION = "browser-bakeoff-result-v1"

#: Fields a single measured (backend, fixture) row must carry. This is a
#: bakeoff artifact, **not** a production ledger: nothing in the runtime reads
#: it and it grants no authority.
RESULT_FIELDS: tuple[str, ...] = (
    "backend",
    "fixture_id",
    "category",
    "required_capabilities",
    "browser_called",
    "browser_state",
    "browser_usable",
    "outcome_state",
    "usable_content",
    "chain_action",
    "chain_reason",
    "attempts",
    "wall_ms",
    "fetch_ms",
    "cold",
    "bytes",
    "content_type",
    "rendered",
    "cache_hit",
    "failure_reason",
    "provenance_complete",
    "budget_respected",
)

#: States that must never be reported as usable content.
NON_USABLE_STATES: frozenset[str] = frozenset(
    {"login_required", "anti_bot", "shell_page"}
)


def build_bakeoff_result(
    *,
    backend: str,
    fixture_id: str,
    category: str,
    required_capabilities: Sequence[str],
    browser_called: bool,
    browser_state: str,
    browser_usable: bool,
    outcome_state: str,
    usable_content: bool,
    chain_action: str,
    chain_reason: str,
    attempts: Sequence[Mapping[str, Any]],
    wall_ms: float,
    fetch_ms: float,
    cold: bool,
    bytes: int,
    content_type: str,
    rendered: bool | None,
    cache_hit: bool | None,
    failure_reason: str,
    provenance_complete: bool,
    budget_respected: bool,
) -> dict[str, Any]:
    """One measured row, in the shape A3-3 compares.

    ``browser_state`` / ``browser_usable`` are the browser step's **own**
    verdict, kept separate from the chain-level ``outcome_state``. Without them
    a fixture where the browser honestly reported ``login_required`` and a later
    step failed differently could not be scored on the browser's honesty.
    """

    result = {
        "backend": str(backend),
        "fixture_id": str(fixture_id),
        "category": str(category),
        "required_capabilities": sorted(str(item) for item in required_capabilities),
        "browser_called": bool(browser_called),
        "browser_state": str(browser_state),
        "browser_usable": bool(browser_usable),
        "outcome_state": str(outcome_state),
        "usable_content": bool(usable_content),
        "chain_action": str(chain_action),
        "chain_reason": str(chain_reason),
        "attempts": [dict(item) for item in attempts],
        "wall_ms": round(float(wall_ms), 1),
        "fetch_ms": round(float(fetch_ms), 1),
        "cold": bool(cold),
        "bytes": int(bytes),
        "content_type": str(content_type),
        "rendered": rendered,
        "cache_hit": cache_hit,
        "failure_reason": str(failure_reason),
        "provenance_complete": bool(provenance_complete),
        "budget_respected": bool(budget_respected),
    }
    validate_bakeoff_result(result)
    return result


def validate_bakeoff_result(result: Mapping[str, Any]) -> None:
    """Fail-closed validation of one bakeoff result row."""

    _require(isinstance(result, Mapping), "result must be a mapping")
    missing = [field for field in RESULT_FIELDS if field not in result]
    _require(not missing, f"result is missing fields: {missing}")
    _require(
        result.get("backend") in CANDIDATE_BACKENDS,
        f"backend must be one of {CANDIDATE_BACKENDS!r}",
    )
    category = str(result.get("category") or "")
    _require(category in BAKEOFF_CLASSES, f"unknown fixture class: {category!r}")
    demand = frozenset(result.get("required_capabilities") or ())
    _require(
        demand <= FROZEN_CAPABILITIES,
        "required_capabilities leaves the frozen vocabulary",
    )
    _require(
        demand == CLASS_CAPABILITY_DEMAND[category],
        f"{category}: required_capabilities must equal the contract",
    )
    state = str(result.get("outcome_state") or "")
    _require(state in RETRIEVAL_STATES, f"outcome_state {state!r} is not canonical")
    browser_state = str(result.get("browser_state") or "")
    _require(
        browser_state == "" or browser_state in RETRIEVAL_STATES,
        f"browser_state {browser_state!r} is not canonical",
    )
    _require(
        str(result.get("chain_action") or "") in ROUTING_ACTIONS,
        "chain_action must be a routing action",
    )
    # The honesty guard: a wall or interstitial is never content - neither at
    # the chain level nor as the browser's own verdict.
    if state in NON_USABLE_STATES:
        _require(
            result.get("usable_content") is False,
            f"{state} must never be reported as usable content",
        )
    if browser_state in NON_USABLE_STATES:
        _require(
            result.get("browser_usable") is False,
            f"the browser reported {browser_state}; that is never usable content",
        )
    if result.get("browser_usable") is True:
        _require(
            browser_state == "success",
            "only a success may be the browser's usable verdict",
        )
    if result.get("usable_content") is True:
        _require(state == "success", "only a success may be usable content")
    # A browser verdict requires a browser call, and vice versa.
    if result.get("browser_called") is True:
        _require(browser_state != "", "a called browser must report a canonical state")
    else:
        _require(
            browser_state == "" and result.get("browser_usable") is False,
            "an uncalled browser must report no verdict",
        )
    # The static-control guard, restated for the result artifact.
    if category == CLASS_STATIC_CONTROL:
        _require(
            result.get("browser_called") is False,
            "static_control must never start a browser",
        )
    _require(
        isinstance(result.get("provenance_complete"), bool),
        "provenance_complete must be a bool",
    )
    _require(
        isinstance(result.get("budget_respected"), bool),
        "budget_respected must be a bool",
    )
    _require(isinstance(result.get("cold"), bool), "cold must be a bool")


def bakeoff_result_document(
    results: Sequence[Mapping[str, Any]], *, backend: str
) -> dict[str, Any]:
    """The artifact written by the harness: one backend's whole fixture run."""

    rows = [dict(item) for item in results]
    for row in rows:
        validate_bakeoff_result(row)
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "bakeoff_version": BAKEOFF_VERSION,
        "backend": str(backend),
        "manifest_schema": SCHEMA_VERSION,
        "budget": dict(BAKEOFF_UNIFIED_BUDGET),
        "results": rows,
    }


__all__ = [
    "ALLOWED_ADAPTER_SURFACE",
    "BAKEOFF_CLASSES",
    "BAKEOFF_DIMENSIONS",
    "BAKEOFF_UNIFIED_BUDGET",
    "BAKEOFF_VERSION",
    "BROWSER_CHAIN_MAX_LENGTH",
    "BrowserBakeoffContractError",
    "CANDIDATE_BACKENDS",
    "CLASS_ANTI_BOT",
    "CLASS_CAPABILITY_DEMAND",
    "CLASS_DOCUMENT_HEAVY",
    "CLASS_EXPECTED_ROUTING",
    "CLASS_EXPECTS_BROWSER_CALL",
    "CLASS_JS_SHELL",
    "CLASS_SESSION_REQUIRED",
    "CLASS_SPA_DELAYED_RENDER",
    "CLASS_STATIC_CONTROL",
    "CLASS_SUCCESS_DEFINITION",
    "FORBIDDEN_CORE_CHANGES",
    "FROZEN_CAPABILITIES",
    "NON_USABLE_STATES",
    "PRODUCTION_CHAIN_AT_A3_0",
    "PROVENANCE_REQUIREMENTS",
    "REQUIRED_DIMENSIONS",
    "RESULT_FIELDS",
    "RESULT_SCHEMA_VERSION",
    "ROUTING_ACTIONS",
    "SCHEMA_VERSION",
    "TARGET_KINDS",
    "WINNER_CRITERIA",
    "bakeoff_result_document",
    "build_bakeoff_result",
    "dimension_keys",
    "intended_browser_chain",
    "load_browser_bakeoff_manifest",
    "required_dimension_keys",
    "validate_bakeoff_result",
    "validate_browser_bakeoff_manifest",
]
