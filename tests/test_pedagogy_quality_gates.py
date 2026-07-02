from pathlib import Path

from src.evals.quality_gates import (
    evaluate_pedagogy_dialogue_case,
    load_eval_cases,
)


FIXTURE = Path(__file__).parent / "fixtures" / "evals" / "pedagogy_dialogues.json"


def test_pedagogy_golden_dialogues_pass_quality_gate():
    cases = load_eval_cases(FIXTURE)
    results = [evaluate_pedagogy_dialogue_case(case) for case in cases]

    assert {case["plan"]["mode"] for case in cases} == {
        "direct_answer",
        "socratic_rediscovery",
        "feynman_diagnosis",
        "project_execution",
    }
    assert len(cases) >= 8
    assert all(result.passed for result in results), {
        result.name: result.failures for result in results if not result.passed
    }
