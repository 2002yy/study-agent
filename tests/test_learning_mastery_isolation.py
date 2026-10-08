"""Learning State-1 §7 / §9: durable-mastery write isolation (T16 / T17 / M6).

Durable mastery is confirmed only by Understanding rows. Those rows are written
exclusively by three ``LearningTruthRepository`` methods::

    create_understanding_evidence
    commit_review_attempt
    commit_semantic_closure

Learning State-1 §7 freezes the only legitimate application-layer writers as the
closure chain (``learning_closure_truth`` / ``learning_semantic_closure``). This
module is the **negative control** for that boundary: if any research (Lookup /
Standard / Deep) or UI / route module starts writing mastery, or if a second
``LearningClosureTruthService`` is constructed, these tests fail.

M6 mutation check: add a call such as ``repo.commit_semantic_closure(...)`` to a
module outside the allowed set (e.g. ``src/web/research/...`` or a route) and
``test_only_the_closure_chain_writes_durable_understanding`` must fail.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

# The three repository methods that create Understanding rows (confirmed mastery).
_UNDERSTANDING_WRITERS = {
    "create_understanding_evidence",
    "commit_review_attempt",
    "commit_semantic_closure",
}

# Allowed application-layer callers, keyed by method. Paths are relative to src/.
_ALLOWED_WRITERS = {
    # No src caller today: it is a repository primitive used by tests and by the
    # two methods below. Any production caller must be added here deliberately.
    "create_understanding_evidence": set(),
    "commit_review_attempt": {"application/learning_closure_truth.py"},
    "commit_semantic_closure": {"application/learning_semantic_closure.py"},
}

# The closure truth service is the single durable-mastery orchestrator.
_CLOSURE_SERVICE_MODULE = "application/runtime_repository.py"

# Only explicit closure entry points may trigger a closure run.
_ALLOWED_CLOSURE_TRIGGERS = {
    "api/routes/learning_closure_routes.py",
    "api/routes/session_routes.py",
}


def _iter_source_files():
    for path in sorted(SRC.rglob("*.py")):
        yield path


def _call_sites(method_names: set[str]) -> dict[str, set[str]]:
    """Map each method name to the set of src-relative files that call it."""
    found: dict[str, set[str]] = {name: set() for name in method_names}
    for path in _iter_source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        relative = path.relative_to(SRC).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in method_names:
                found[func.attr].add(relative)
    return found


def _call_sites_in_routes(method_name: str) -> set[str]:
    """Call sites of a method restricted to src/api/routes."""
    routes = SRC / "api" / "routes"
    found: set[str] = set()
    for path in sorted(routes.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == method_name:
                    found.add(path.relative_to(SRC).as_posix())
    return found


def test_only_the_closure_chain_writes_durable_understanding():
    call_sites = _call_sites(_UNDERSTANDING_WRITERS)
    for method, allowed in _ALLOWED_WRITERS.items():
        offenders = call_sites[method] - allowed
        assert not offenders, (
            f"{method} is called outside the closure chain: {sorted(offenders)}; "
            "durable mastery must only be written by the closure path (§7 / M6)"
        )


def test_create_understanding_evidence_has_no_production_caller():
    # If a production caller appears it must be reviewed and allow-listed above;
    # until then the primitive stays test-only.
    assert _call_sites({"create_understanding_evidence"})[
        "create_understanding_evidence"
    ] == set()


def test_closure_truth_service_is_constructed_only_by_the_runtime_wiring():
    offenders: set[str] = set()
    for path in _iter_source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "LearningClosureTruthService":
                relative = path.relative_to(SRC).as_posix()
                if relative != _CLOSURE_SERVICE_MODULE:
                    offenders.add(relative)
    assert not offenders, (
        f"LearningClosureTruthService constructed outside runtime wiring: {sorted(offenders)}"
    )


def test_only_explicit_closure_routes_trigger_a_closure_run():
    offenders = _call_sites_in_routes("create_and_execute") - _ALLOWED_CLOSURE_TRIGGERS
    assert not offenders, (
        f"closure run triggered from a non-closure route: {sorted(offenders)}"
    )
