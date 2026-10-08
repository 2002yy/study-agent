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

# --- machine-stable fields the workflow consumes --------------------------------


def test_stable_fields_are_all_present():
    result = classify(['src/web/research/runtime.py'])
    for key in (
        'scope', 'frontend_required', 'browser_required', 'qualification_required',
        'l3_eligible', 'l3_required_for_merge', 'full_scope',
    ):
        assert key in result, key


def test_browser_required_only_for_browser_or_unknown():
    assert classify(['src/web/research/runtime.py'])['browser_required'] is False
    assert classify(['src/web/research/crawl4ai_worker.py'])['browser_required'] is True
    assert classify(['mystery/x.bin'])['browser_required'] is True


def test_qualification_required_only_for_qualification_or_unknown():
    assert classify(['src/web/research/runtime.py'])['qualification_required'] is False
    assert classify(['tests/test_rq1c_protocol_probes.py'])['qualification_required'] is True


def test_eligibility_is_reported_not_acted_on():
    # A shared-core change is eligible to be part of a final L3 candidate, but the field
    # is only a report and L3 is never required per merge by the classifier.
    result = classify(['src/domain/evidence.py'])
    assert result['l3_eligible'] is True
    assert result['l3_required_for_merge'] is False
    assert 'action' not in result

def test_ci_tooling_paths_are_recognised():
    for path in (
        '.github/workflows/ci.yml',
        '.github/workflows/ci-l3.yml',
        'tools/ci_scope.py',
        'tools/check_ci_outcomes.py',
    ):
        assert classify_path(path) == 'ci-tooling', path


def test_ci_tooling_does_not_require_frontend_or_l3():
    result = classify(['tools/ci_scope.py', '.github/workflows/ci.yml'])
    assert result['frontend_required'] is False
    assert result['browser_required'] is False
    assert result['l3_eligible'] is False
    assert result['full_scope'] is False

def test_l3_preflight_test_is_ci_tooling():
    assert classify_path('tests/test_l3_preflight.py') == 'ci-tooling'


def test_a_real_ci_tooling_change_set_is_not_unknown_and_not_full():
    # The exact paths of the CI-tiering pull request itself: none may be unknown, so the
    # fast tier can actually engage instead of widening to the full gate.
    paths = [
        '.github/workflows/ci-l3.yml', '.github/workflows/ci.yml', 'AGENTS.md',
        'tests/test_ci_outcomes.py', 'tests/test_ci_scope.py', 'tests/test_l3_preflight.py',
        'tools/check_ci_outcomes.py', 'tools/ci_scope.py', 'tools/l3_preflight.py',
    ]
    result = classify(paths)
    assert result['unknown_paths'] == []
    assert result['full_scope'] is False
    assert result['frontend_required'] is False
    assert result['scope'] == 'tiered'


# --- CI-2: standard routing, named impact sets, eligibility vs requirement ---------


def test_standard_paths_are_recognised():
    assert classify_path("tests/test_standard_research.py") == "standard"
    assert classify_path("src/application/standard_execution.py") == "standard"
    assert classify_path("src/repositories/standard_execution_repository.py") == "standard"


def test_standard_change_is_not_unknown_and_not_full():
    result = classify(["tests/test_standard_research.py", "src/application/standard_handoff.py"])
    assert result["unknown_paths"] == []
    assert result["full_scope"] is False
    assert result["frontend_required"] is False


def test_standard_change_selects_the_named_impact_set():
    result = classify(["tests/test_standard_research.py"])
    assert result["impact_set"] == "standard_research_loop"


def test_unregistered_research_change_falls_back_to_full_scope():
    # No broad "any research path" mapping: an unregistered subsystem must not be routed
    # to a narrower set than it needs, so it yields no impact set and the full suite runs.
    result = classify(["src/web/research/runtime.py"])
    assert result["impact_set"] == ""
    assert result["full_scope"] is False


def test_multi_category_change_has_no_single_impact_set():
    result = classify(["src/web/research/runtime.py", "tests/test_standard_research.py"])
    assert result["impact_set"] == ""
    assert result["full_scope"] is False


def test_unknown_path_yields_no_impact_set_and_full_scope():
    result = classify(["mystery/thing.bin"])
    assert result["impact_set"] == ""
    assert result["full_scope"] is True


def test_ci_tooling_change_has_no_impact_set():
    # A CI-tooling-only change is not covered by a product impact set; the workflow must
    # fall back safely rather than guess one.
    result = classify(["tools/ci_scope.py", ".github/workflows/ci.yml"])
    assert result["impact_set"] == ""


def test_eligibility_and_requirement_are_decoupled():
    # Registering an impact set touches the qualification category: eligible, but an
    # intermediate slice must not be reported as requiring L3 before merge.
    result = classify(["tests/stage_gates.json"])
    assert result["l3_eligible"] is True
    assert result["l3_required_for_merge"] is False


# --- CI-2 review fixes: a real slice carries docs and a gate registration -----------


def test_real_standard_slice_still_selects_its_impact_set():
    # A real Standard slice also touches docs and registers its impact set. Those must
    # not blank the impact set and send the pull request back to the full suite.
    result = classify([
        "tests/test_standard_research.py",
        "src/application/standard_handoff.py",
        "docs/PROJECT_STATUS.md",
        "tests/stage_gates.json",
    ])
    assert result["full_scope"] is False
    assert result["impact_set"] == "standard_research_loop"
    assert result["categories"] == ["docs", "qualification", "standard"]


def test_docs_and_gate_registration_alone_select_no_impact_set():
    result = classify(["docs/PROJECT_STATUS.md", "tests/stage_gates.json"])
    assert result["impact_set"] == ""
    assert result["full_scope"] is False


def test_product_category_without_a_mapping_yields_no_impact_set():
    # learning-backend has no named set, so the fast tier must fall back safely rather
    # than guess one.
    result = classify(["src/application/chat_service.py"])
    assert result["impact_set"] == ""
    assert result["full_scope"] is False


def test_unknown_still_wins_over_a_mapped_category():
    result = classify(["tests/test_standard_research.py", "mystery/x.bin"])
    assert result["impact_set"] == ""
    assert result["full_scope"] is True


# --- CI-2 review fix: a Standard research module is a Standard change ---------------


def test_standard_research_module_routes_to_the_standard_set():
    result = classify(["src/web/research/standard_plan.py"])
    assert result["categories"] == ["standard"]
    assert result["impact_set"] == "standard_research_loop"


def test_standard_research_module_beats_the_broader_research_rule():
    # The standard rule is checked before the general research rule.
    assert classify_path("src/web/research/standard_plan.py") == "standard"
    assert classify_path("src/web/research/runtime.py") == "research-backend"


# --- third review: only prose and the manifest attachment are neutral -----------------


def test_standard_plus_a_real_qualification_change_is_not_narrowed():
    # A protocol-probe change is a real change, not an attachment: it must not be treated
    # as riding along with the Standard slice.
    result = classify([
        "tests/test_standard_research.py",
        "tests/test_rq1c_protocol_probes.py",
    ])
    assert result["impact_set"] == ""
    assert result["full_scope"] is False


def test_standard_plus_a_ci_tooling_change_is_not_narrowed():
    result = classify([
        "tests/test_standard_research.py",
        "tools/ci_scope.py",
    ])
    assert result["impact_set"] == ""
    assert result["full_scope"] is False


def test_standard_plus_docs_and_manifest_attachment_is_still_narrowed():
    result = classify([
        "tests/test_standard_research.py",
        "docs/PROJECT_STATUS.md",
        "tests/stage_gates.json",
    ])
    assert result["impact_set"] == "standard_research_loop"


def test_manifest_alone_is_not_a_slice():
    result = classify(["tests/stage_gates.json"])
    assert result["impact_set"] == ""
    assert result["full_scope"] is False


def test_other_qualification_path_alone_is_not_a_slice():
    result = classify(["tests/test_rq1c_protocol_probes.py"])
    assert result["impact_set"] == ""
    assert result["full_scope"] is False
