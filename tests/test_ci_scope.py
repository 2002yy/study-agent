"""CI scope routing: each category, and the negative controls that matter."""

from __future__ import annotations

from tools.ci_scope import classify, classify_path


# --- path classification --------------------------------------------------------


def test_research_paths_are_research_backend():
    assert classify_path("src/web/research/runtime.py") == "research-backend"
    assert classify_path("tools/run_research_calibration.py") == "research-backend"


def test_frontend_paths_are_frontend():
    assert classify_path("frontend/src/App.tsx") == "frontend"


def test_domain_and_sqlite_are_shared_core():
    assert classify_path("src/domain/evidence.py") == "shared-core"
    assert classify_path("src/infrastructure/sqlite/database.py") == "shared-core"


def test_repositories_are_persistence():
    assert classify_path("src/repositories/web_lookup_repository.py") == "persistence"


def test_qualification_paths_are_qualification():
    assert classify_path("tests/test_rq1c_protocol_probes.py") == "qualification"
    assert classify_path("tests/stage_gates.json") == "qualification"
    assert classify_path("tools/l3_preflight.py") == "qualification"


def test_docs_are_docs():
    assert classify_path("docs/PROJECT_STATUS.md") == "docs"
    assert classify_path("AGENTS.md") == "docs"


def test_unknown_path_is_unknown():
    assert classify_path("some/new/thing.xyz") == "unknown"


# --- derived gates: the controls that matter ------------------------------------


def test_research_only_diff_does_not_require_frontend_or_browser():
    result = classify(["src/web/research/runtime.py", "tools/run_research_calibration.py"])
    assert result["frontend_required"] is False
    assert result["full_scope"] is False
    assert result["scope"] == "research-backend-only"


def test_frontend_only_diff_does_not_require_research_qualification():
    result = classify(["frontend/src/App.tsx", "frontend/package.json"])
    assert result["categories"] == ["frontend"]
    assert result["frontend_required"] is True
    assert result["l3_eligible"] is False


def test_shared_core_widens_the_gate_and_is_l3_eligible():
    result = classify(["src/domain/evidence.py"])
    assert result["l3_eligible"] is True
    assert result["frontend_required"] is False


def test_qualification_change_is_l3_eligible():
    result = classify(["tests/stage_gates.json"])
    assert result["l3_eligible"] is True


def test_unknown_path_is_conservative():
    result = classify(["mystery/file.bin"])
    assert result["full_scope"] is True
    assert result["frontend_required"] is True
    assert result["l3_eligible"] is True
    assert result["unknown_paths"] == ["mystery/file.bin"]


def test_pure_docs_change_requires_nothing_heavy():
    result = classify(["docs/PROJECT_STATUS.md", "AGENTS.md"])
    assert result["categories"] == ["docs"]
    assert result["frontend_required"] is False
    assert result["l3_eligible"] is False
    assert result["full_scope"] is False


def test_mixed_change_unions_the_categories():
    result = classify(["src/web/research/runtime.py", "frontend/src/App.tsx"])
    assert result["categories"] == ["frontend", "research-backend"]
    assert result["frontend_required"] is True
    assert result["l3_eligible"] is False
