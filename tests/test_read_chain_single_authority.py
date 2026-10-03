"""§143-B0 anti-bypass regression.

The measurement seam is only trustworthy while ``execute()`` and the narrow
measurement entry share ONE implementation authority. If ``execute()`` ever
re-inlines its own executor construction, a measurement could silently observe a
hand-rolled "equivalent" of the production default and §143-B would lose its
meaning.

This is a source-level structural guard, deliberately cheap and blunt.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = REPO_ROOT / "src" / "application" / "active_research_runtime.py"


def _source() -> str:
    return RUNTIME.read_text(encoding="utf-8")


def test_active_reader_chain_is_module_level_and_importable() -> None:
    """The chain must be a stable contract, not a function-local name."""

    from src.application.active_research_runtime import ACTIVE_READER_CHAIN

    assert ACTIVE_READER_CHAIN == ("native_http", "wigolo_http")

    tree = ast.parse(_source())
    # exactly one module-level assignment (plain or annotated)
    module_level = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if any(
            isinstance(t, ast.Name) and t.id == "ACTIVE_READER_CHAIN" for t in targets
        ):
            module_level.append(node)
    assert len(module_level) == 1, "ACTIVE_READER_CHAIN must be module-level exactly once"


def test_shared_primitive_exists_and_is_used_by_execute() -> None:
    """`build_read_chain_executors` exists and execute() delegates to it."""

    from src.application import active_research_runtime as mod

    assert callable(mod.build_read_chain_executors)

    src = _source()
    assert src.count("def build_read_chain_executors(") == 1
    # the in-method wrapper must call the shared primitive
    assert "return build_read_chain_executors(" in src


def test_read_semantics_primitive_is_the_only_authority() -> None:
    """§143-B0.1: read semantics live in ONE module-level primitive."""

    from src.application import active_research_runtime as mod

    assert callable(mod.build_production_gateway_read)

    src = _source()
    assert src.count("def build_production_gateway_read(") == 1, (
        "read semantics must have exactly one implementation authority"
    )
    # both the production execute() path and the measurement entry build the
    # read function through the same primitive
    assert src.count("= build_production_gateway_read(") == 2, (
        "execute() and run_single_read_measurement must both use the shared primitive"
    )
    # the read function itself must be declared in exactly one place (inside
    # the shared primitive), never re-inlined in execute()/measurement
    assert src.count("def gateway_read(") == 1, (
        "gateway_read must only be produced by the shared primitive, never re-inlined"
    )
    # escalation runtime context must not be forked into a second call site
    assert src.count("set_escalation_runtime_context(") == 1, (
        "escalation runtime context must be stamped by the shared primitive only"
    )
    # the read timeout must not be re-implemented outside the primitive
    assert "def read_timeout_seconds(" not in src, (
        "read timeout semantics must live in the shared primitive only"
    )


def test_measurement_entry_accepts_no_arbitrary_gateway_read() -> None:
    """§143-B0.1: a caller may not inject a hand-rolled read function."""

    import inspect

    from src.application import active_research_runtime as mod

    params = inspect.signature(mod.run_single_read_measurement).parameters
    assert "gateway_read" not in params, (
        "the measurement entry must not accept an arbitrary gateway_read"
    )
    # the low-level gateway is injected; the read *semantics* are not
    assert "gateway" in params
    assert "research_seconds_left" in params


def test_executor_construction_is_not_re_inlined() -> None:
    """Only the shared primitive may construct the reader executors."""

    src = _source()
    # the primitive itself is the single allowed construction site
    assert src.count("NativeHttpBackendExecutor(read_fn=") == 1, (
        "execute() must not re-inline its own native executor construction"
    )
    assert src.count("WigoloHttpBackendExecutor(") == 1, (
        "execute() must not re-inline its own wigolo executor construction"
    )


def test_measurement_entry_does_not_start_orchestration() -> None:
    """The narrow entry must share the primitive and never start orchestration."""

    from src.application import active_research_runtime as mod

    assert callable(mod.run_single_read_measurement)

    src = _source()
    match = re.search(
        r"def run_single_read_measurement\(.*?\n(?=\nclass |\ndef |\Z)",
        src,
        re.DOTALL,
    )
    assert match is not None, "narrow measurement entry must exist"
    body = match.group(0)
    # scan the CODE only: the docstring legitimately names what it must not do
    parts = body.split('"""')
    code = parts[0] + (parts[2] if len(parts) >= 3 else "")

    # shares the one implementation authority + real run_chain
    assert "build_read_chain_executors(" in code
    assert "run_chain(" in code
    assert "chain=ACTIVE_READER_CHAIN" in code

    # never starts unrelated research orchestration
    for forbidden in ("execute(", "discover", "synthes"):
        assert forbidden not in code, f"measurement entry must not call {forbidden!r}"

    # carries no routing/deadline/budget logic of its own
    for forbidden in ("route(", "schedulable_now(", "deadline_preflight(", "budget"):
        assert forbidden not in code, f"measurement entry must not re-implement {forbidden!r}"
