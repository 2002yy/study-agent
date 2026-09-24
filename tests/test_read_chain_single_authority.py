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
    """The narrow entry must not pull in discovery/planning/synthesis."""

    src = _source()
    match = re.search(
        r"def run_single_read_measurement\(.*?\n(?=\nclass |\ndef |\Z)",
        src,
        re.DOTALL,
    )
    if match is None:
        # not implemented yet: the guard is a placeholder until B0 lands it
        return
    body = match.group(0)
    for forbidden in ("discover", "plan(", "synthes", "execute("):
        assert forbidden not in body, f"measurement entry must not call {forbidden!r}"
