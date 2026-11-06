"""Batch-C closure matrix for failure, stop, API and UI truth.

Batch C locks the full writer -> catalog -> durable stop -> consumer path. The
stop audit inspects actual stop_reason arguments/assignments (plus migration SQL)
in both directions; unrelated provider_status strings or comments cannot satisfy
it. Repository new-writer methods additionally fail closed at runtime, while
readers and API transport remain forward-compatible strings.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest

from src.api.models.news import WebLookupRunResponse
from src.application.research_stop_gate import ResearchStopGate, ResearchStopSignal
from src.domain.runtime_entities import WebLookupRun
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.failure_contracts import (
    RESEARCH_FAILURE_CODES,
    RESEARCH_STOP_REASONS,
    require_research_stop_reason,
)

ROOT = Path(__file__).resolve().parents[1]

FAILURE_WRITER_PATHS = (
    "src/application/active_research_runtime.py",
    "src/web/research/runtime.py",
)
STOP_AST_WRITER_PATHS = (
    "src/application/research_stop_gate.py",
    "src/application/active_research_runtime.py",
    "src/application/web_lookup_service.py",
)
STOP_SQL_WRITER_PATHS = (
    "src/repositories/web_lookup_repository.py",
    "src/infrastructure/sqlite/database.py",
)
UI_CATALOG_PATH = "frontend/src/features/web-lookup/researchStopReason.ts"
UI_CONSUMER_PATH = "frontend/src/features/web-lookup/ChatResearchRecovery.tsx"
UI_TRANSPORT_PATH = "frontend/src/features/web-lookup/researchApi.ts"
API_ROUTE_PATH = "src/api/routes/web_lookup_routes.py"


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _api_response(stop_reason: str) -> WebLookupRunResponse:
    return WebLookupRunResponse(
        id="research-matrix-1",
        query="matrix contract",
        status="completed",
        items=[],
        source_block="",
        warnings=[],
        error="",
        stop_reason=stop_reason,
        version=1,
        created_at="2026-09-02T00:00:00Z",
        updated_at="2026-09-02T00:00:01Z",
        completed_at="2026-09-02T00:00:01Z",
    )


def _function_return_literals(tree: ast.Module) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        values = {
            child.value.value
            for child in ast.walk(node)
            if isinstance(child, ast.Return)
            and isinstance(child.value, ast.Constant)
            and isinstance(child.value.value, str)
            and child.value.value
        }
        if values:
            result[node.name] = values
    return result


def _expr_literals(
    node: ast.AST,
    names: dict[str, set[str]],
    function_returns: dict[str, set[str]],
) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value} if node.value else set()
    if isinstance(node, ast.Name):
        return set(names.get(node.id, set()))
    if isinstance(node, ast.IfExp):
        return _expr_literals(node.body, names, function_returns) | _expr_literals(
            node.orelse, names, function_returns
        )
    if isinstance(node, ast.BoolOp):
        return set().union(
            *(_expr_literals(value, names, function_returns) for value in node.values)
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return set(function_returns.get(node.func.id, set()))
    return set()


def _function_name_values(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    function_returns: dict[str, set[str]],
) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    changed = True
    while changed:
        changed = False
        for child in ast.walk(node):
            if not isinstance(child, (ast.Assign, ast.AnnAssign)):
                continue
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            value = child.value
            if value is None:
                continue
            literals = _expr_literals(value, names, function_returns)
            if not literals:
                continue
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                before = set(names.get(target.id, set()))
                after = before | literals
                if after != before:
                    names[target.id] = after
                    changed = True
    return names


def _ast_stop_writer_literals(path: str) -> set[str]:
    tree = ast.parse(_source(path))
    function_returns = _function_return_literals(tree)
    result: set[str] = set()

    scopes: list[tuple[ast.AST, dict[str, set[str]]]] = [(tree, {})]
    scopes.extend(
        (node, _function_name_values(node, function_returns))
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    for scope, names in scopes:
        for node in ast.walk(scope):
            if not isinstance(node, ast.Call):
                continue
            func = node.func.attr if isinstance(node.func, ast.Attribute) else (
                node.func.id if isinstance(node.func, ast.Name) else ""
            )
            for keyword in node.keywords:
                is_repository_stop = keyword.arg == "stop_reason" and func in {
                    "checkpoint",
                    "complete",
                    "fail",
                }
                is_stop_gate_reason = keyword.arg == "reason" and func in {
                    "ResearchStopDecision",
                    "_terminal_unavailable",
                }
                is_unavailable_signal = (
                    keyword.arg == "unavailable_reason" and func == "ResearchStopSignal"
                )
                if is_repository_stop or is_stop_gate_reason or is_unavailable_signal:
                    result |= _expr_literals(keyword.value, names, function_returns)
    return result


def _sql_stop_writer_literals(path: str) -> set[str]:
    source = _source(path)
    result = set(re.findall(r"stop_reason\s*=\s*'([a-z0-9_]+)'", source))
    for block in re.findall(
        r"SET\s+stop_reason\s*=\s*CASE(.*?)END\s*;",
        source,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        result.update(re.findall(r"THEN\s+'([a-z0-9_]+)'", block, flags=re.IGNORECASE))

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args.args
        defaults = node.args.defaults
        offset = len(args) - len(defaults)
        for index, default in enumerate(defaults, start=offset):
            if args[index].arg != "stop_reason":
                continue
            if isinstance(default, ast.Constant) and isinstance(default.value, str) and default.value:
                result.add(default.value)
    return result


def _actual_stop_writer_literals() -> set[str]:
    return set().union(
        *(_ast_stop_writer_literals(path) for path in STOP_AST_WRITER_PATHS),
        *(_sql_stop_writer_literals(path) for path in STOP_SQL_WRITER_PATHS),
    )


def test_writer_side_stop_guard_is_closed_but_reader_contract_is_not() -> None:
    assert require_research_stop_reason("evidence_gate_pass") == "evidence_gate_pass"
    with pytest.raises(ValueError):
        require_research_stop_reason("future_provider_specific_stop")

    future = "future_provider_specific_stop"
    assert _api_response(future).stop_reason == future


def test_stop_gate_rejects_an_unregistered_new_writer_reason() -> None:
    with pytest.raises(ValueError, match="unknown research stop reason"):
        ResearchStopGate.evaluate(
            ResearchStopSignal(
                gate_pass=False,
                hard_budget_exhausted=False,
                has_actionable_gaps=True,
                all_actionable_saturated=False,
                wave_limit_reached=False,
                has_evidence=False,
                unavailable_reason="provider_timeout",
            )
        )


def test_repository_rejects_unregistered_new_writer_reason(tmp_path: Path) -> None:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.sqlite3"))
    future = "future_provider_specific_stop"
    with pytest.raises(ValueError, match="unknown research stop reason"):
        repository.create(WebLookupRun(query="invalid create", status="pending", stop_reason=future))

    created = repository.create(WebLookupRun(query="writer guard", status="pending"))
    running = repository.begin_operation(
        created.id,
        operation_id="operation-writer-guard",
        stage="searching",
    )
    common = {
        "operation_id": "operation-writer-guard",
        "research_context": running.research_context,
        "query_attempts": [],
        "selected_sources": [],
        "rejected_sources": [],
        "items": [],
        "warnings": [],
    }
    with pytest.raises(ValueError, match="unknown research stop reason"):
        repository.checkpoint(running.id, stop_reason=future, **common)
    with pytest.raises(ValueError, match="unknown research stop reason"):
        repository.complete(
            running.id,
            items=[],
            source_block="",
            warnings=[],
            stop_reason=future,
            operation_id="operation-writer-guard",
        )
    with pytest.raises(ValueError, match="unknown research stop reason"):
        repository.fail(
            running.id,
            "provider detail",
            stop_reason=future,
            operation_id="operation-writer-guard",
        )
    assert repository.get(running.id).stop_reason == ""


def test_failure_catalog_has_a_production_writer_surface() -> None:
    writer_source = "\n".join(_source(path) for path in FAILURE_WRITER_PATHS)
    missing = sorted(
        code for code in RESEARCH_FAILURE_CODES if f'"{code}"' not in writer_source
    )
    assert missing == []


def test_stop_writers_and_catalog_are_closed_in_both_directions() -> None:
    writers = _actual_stop_writer_literals()
    assert sorted(writers - RESEARCH_STOP_REASONS) == []
    assert sorted(RESEARCH_STOP_REASONS - writers) == []


def test_api_preserves_every_canonical_stop_reason_verbatim() -> None:
    for reason in RESEARCH_STOP_REASONS:
        response = _api_response(reason)
        assert response.stop_reason == reason
        assert response.model_dump()["stop_reason"] == reason

    route_source = _source(API_ROUTE_PATH)
    # Additional display-only fields may be projected here; the canonical run
    # remains spread unchanged, preserving every stop reason.
    assert "WebLookupRunResponse(" in route_source
    assert "**asdict(run)" in route_source

    transport_source = _source(UI_TRANSPORT_PATH)
    assert "stop_reason: run.stop_reason" in transport_source


def test_ui_display_catalog_exactly_matches_backend_stop_catalog() -> None:
    source = _source(UI_CATALOG_PATH)
    match = re.search(
        r"KNOWN_RESEARCH_STOP_REASONS\s*=\s*\[(.*?)\]\s*as const",
        source,
        flags=re.DOTALL,
    )
    assert match is not None
    ui_reasons = set(re.findall(r'"([a-z0-9_]+)"', match.group(1)))
    assert ui_reasons == RESEARCH_STOP_REASONS


def test_ui_unknown_reason_has_a_safe_non_echo_fallback() -> None:
    catalog_source = _source(UI_CATALOG_PATH)
    assert (
        "RESEARCH_STOP_REASON_LABELS[reason as KnownResearchStopReason] ?? fallback"
        in catalog_source
    )
    assert "return reason" not in catalog_source

    consumer_source = _source(UI_CONSUMER_PATH)
    assert "researchStopReasonDisplay" in consumer_source
    assert "progress.stop_reason ??" not in consumer_source
    assert "run.stop_reason ||" not in consumer_source
    assert "progress.error ||" not in consumer_source
    assert "run.error ||" not in consumer_source
