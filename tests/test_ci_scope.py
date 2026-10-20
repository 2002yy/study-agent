"""CI scope routing: each category, and the negative controls that matter."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.ci_scope import classify, classify_path


def test_exact_conversation_decision_paths_select_their_registered_impact_set():
    paths = [
        "src/application/conversation_decision.py",
        "src/application/conversation_decision_runner.py",
        "tests/test_conversation_decision.py",
        "tests/test_conversation_decision_runner.py",
        "src/application/conversation_action_dispatch.py",
        "src/application/conversation_action_step.py",
        "src/application/conversation_observation_followup.py",
        "src/application/conversation_bounded_loop.py",
        "src/application/conversation_loop_session.py",
        "tests/test_conversation_action_dispatch.py",
        "tests/test_conversation_action_step.py",
        "tests/test_conversation_observation_followup.py",
        "tests/test_conversation_bounded_loop.py",
        "tests/test_conversation_loop_session.py",
        "src/application/conversation_observation_trail.py",
        "tests/test_conversation_observation_trail.py",
        "src/application/conversation_answer_input.py",
        "tests/test_conversation_answer_input.py",
        "src/application/conversation_answer_runner.py",
        "tests/test_conversation_answer_runner.py",
        "src/application/conversation_answer_generator.py",
        "tests/test_conversation_answer_generator.py",
        "src/application/conversation_deepseek_transport.py",
        "tests/test_conversation_deepseek_transport.py",
        "src/application/conversation_deepseek_session.py",
        "tests/test_conversation_deepseek_session.py",
    ]
    for path in paths:
        result = classify([path])
        assert classify_path(path) == "conversation-decision"
        assert result["impact_set"] == "conversation_decision_1b"
        assert not result["full_scope"]
        assert not result["frontend_required"]
        assert not result["browser_required"]
        assert not result["qualification_required"]
    result = classify(paths + ["docs/PROJECT_STATUS.md", "tests/stage_gates.json"])
    assert result["impact_set"] == "conversation_decision_1b"


def test_conversation_mapping_resolves_to_real_tests_and_covers_both_modules():
    from tools.run_stage_gate import load_manifest, resolve

    paths = resolve(load_manifest(), impact_set="conversation_decision_1b")
    assert "tests/test_conversation_decision.py" in paths
    assert "tests/test_conversation_decision_runner.py" in paths


def test_loop_mapping_covers_actual_modules_and_complete_registered_consumer_stack():
    from tools.run_stage_gate import load_manifest, resolve

    paths = resolve(load_manifest(), impact_set="conversation_decision_1b")
    root = Path(__file__).resolve().parents[1]
    for name in (
        "conversation_action_dispatch", "conversation_action_step",
        "conversation_observation_followup", "conversation_bounded_loop",
        "conversation_loop_session",
        "conversation_observation_trail",
        "conversation_answer_input",
        "conversation_answer_runner",
        "conversation_answer_generator",
        "conversation_deepseek_transport",
        "conversation_deepseek_session",
    ):
        module = f"src/application/{name}.py"
        test = f"tests/test_{name}.py"
        assert (root / module).is_file() and (root / test).is_file()
        assert test in paths
        assert classify([module.replace("/", "\\"), test])["impact_set"] == "conversation_decision_1b"
    # The ledger is a dependency, but changing its persistence code is not
    # classified as an ordinary loop slice by this patch.
    assert "tests/test_conversation_decision_admission.py" in paths


@pytest.mark.parametrize("impact,consumers", [
    ("conversation_action_dispatch", {
        "tests/test_conversation_action_step.py", "tests/test_conversation_observation_followup.py",
        "tests/test_conversation_bounded_loop.py", "tests/test_conversation_loop_session.py",
    }),
    ("conversation_action_step", {"tests/test_conversation_observation_followup.py"}),
    ("conversation_observation_followup", {"tests/test_conversation_bounded_loop.py", "tests/test_conversation_observation_trail.py"}),
    ("conversation_bounded_loop", {"tests/test_conversation_loop_session.py"}),
])
def test_named_development_gates_retain_new_direct_consumers(impact, consumers):
    from tools.run_stage_gate import load_manifest, resolve

    paths = resolve(load_manifest(), impact_set=impact)
    assert consumers <= set(paths)


@pytest.mark.parametrize("name", [
    "conversation_action_dispatch", "conversation_action_step",
    "conversation_observation_followup", "conversation_bounded_loop",
    "conversation_loop_session",
])
@pytest.mark.parametrize("adjacent", [
    "src/application/conversation_decision_admission.py",
    "src/application/conversation_decision_context.py",
    "src/infrastructure/sqlite/database.py", "src/domain/evidence.py",
    "mystery/new.py",
])
def test_loop_slice_mixed_with_persistence_or_unregistered_paths_cannot_narrow(name, adjacent):
    result = classify([f"src/application/{name}.py", adjacent])
    assert result["impact_set"] == ""
    assert classify_path(adjacent) != "conversation-decision"


def test_conversation_prefix_is_not_a_blanket_subsystem_exclusion():
    for path in (
        "src/application/conversation_decision_new.py",
        "src/application/chat_service.py",
        "tests/test_conversation_decision_other.py",
        "src/application/conversation_action_dispatch_new.py",
        "src/application/conversation_bounded_loop_new.py",
        "tests/test_conversation_loop_session_new.py",
        "src/application/conversation_observation_trail_new.py",
        "tests/test_conversation_observation_trail_new.py",
    ):
        result = classify(["src/application/conversation_decision.py", path])
        assert result["impact_set"] == ""
        assert classify_path(path) != "conversation-decision"


def test_conversation_mixed_with_real_infrastructure_never_narrows_the_gate():
    for path in (
        "tools/ci_scope.py", "tests/test_ci_scope.py",
        "src/domain/runtime_entities.py", "src/infrastructure/sqlite/database.py",
        "src/web/research/standard_execution.py", "frontend/src/types.ts",
        "tests/test_rq1c_protocol_probes.py", "unknown/file.py",
    ):
        result = classify(["src/application/conversation_decision.py", path])
        assert result["impact_set"] == "", path


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
