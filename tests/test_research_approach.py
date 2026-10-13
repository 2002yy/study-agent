"""Research opening ("研究开场") display contract — deterministic unit tests."""

from __future__ import annotations

import json

import pytest

from src.web.research.research_approach import (
    APPROACH_SCHEMA,
    approach_event,
    direction_update,
    fallback_approach,
    generate_approach,
    generate_approach_or_fallback,
    normalize_mode,
    project_from_plan,
    seed_approach,
    validate_approach,
)

# No approach object may ever carry evidence authority.
_FORBIDDEN_KEYS = {
    "evidence_ids",
    "supported",
    "publication_authority",
    "evidence_rows",
    "answer_hash",
}


def _assert_no_authority(approach: dict) -> None:
    assert not (_FORBIDDEN_KEYS & set(approach))


def test_seed_is_pending_and_authority_free() -> None:
    seed = seed_approach(mode="standard", turn_id="turn_1")
    assert seed["schema"] == APPROACH_SCHEMA
    assert seed["status"] == "pending"
    assert seed["summary"] == ""
    assert seed["sequence"] == 0
    _assert_no_authority(seed)


def test_normalize_mode_maps_unknown_to_standard() -> None:
    assert normalize_mode("lookup") == "lookup"
    assert normalize_mode("DEEP") == "deep"
    assert normalize_mode("weird") == "standard"
    assert normalize_mode(None) == "standard"


def test_project_from_plan_is_ready_and_preferred_origin() -> None:
    approach = project_from_plan(
        mode="deep",
        summary="我会先建立候选清单，再分别验证核心功能与自动化接口。",
        focus=["候选清单", "功能覆盖", "自动化接口"],
    )
    assert approach["status"] == "ready"
    assert approach["origin"] == "model_plan"
    assert approach["sequence"] == 1
    assert approach["focus"] == ["候选清单", "功能覆盖", "自动化接口"]
    _assert_no_authority(approach)


def test_validate_rejects_envelope_and_enum_errors() -> None:
    with pytest.raises(ValueError):
        validate_approach({"schema": "wrong"})
    with pytest.raises(ValueError):
        validate_approach(
            {
                "schema": APPROACH_SCHEMA,
                "mode": "standard",
                "status": "nope",
                "origin": "fallback",
                "summary": "",
                "sequence": 0,
            }
        )
    with pytest.raises(ValueError):
        validate_approach(
            {
                "schema": APPROACH_SCHEMA,
                "mode": "standard",
                "status": "pending",
                "origin": "invented",
                "summary": "",
                "sequence": 0,
            }
        )


def test_ready_requires_nonempty_summary() -> None:
    with pytest.raises(ValueError):
        project_from_plan(mode="lookup", summary="   ")


def test_summary_length_is_mode_bounded() -> None:
    long_summary = "研究维度" * 60  # 240 chars
    with pytest.raises(ValueError):
        project_from_plan(mode="lookup", summary=long_summary)  # limit 140
    # Standard allows more.
    assert project_from_plan(mode="standard", summary=long_summary)["summary"]


def test_filler_opening_is_rejected() -> None:
    with pytest.raises(ValueError):
        project_from_plan(mode="standard", summary="让我看看这个问题，我会比较一下。")


def test_unverified_completion_claim_is_rejected() -> None:
    with pytest.raises(ValueError):
        project_from_plan(mode="standard", summary="我会比较已核验的官方文档结论。")


def test_duplicate_of_previous_summary_is_rejected() -> None:
    previous = project_from_plan(mode="standard", summary="我会比较各方案的功能与兼容性。")
    with pytest.raises(ValueError):
        direction_update(previous=previous, summary="我会比较各方案的功能与兼容性。")


def test_direction_update_continues_and_allows_progress_claims() -> None:
    previous = project_from_plan(mode="standard", summary="我会比较各方案的功能与兼容性。")
    updated = direction_update(
        previous=previous,
        summary="标准研究已经确认了部分功能，我会继续核对自动化接口这个缺口。",
        mode="deep",
    )
    assert updated["origin"] == "direction_update"
    assert updated["sequence"] == previous["sequence"] + 1
    assert updated["mode"] == "deep"
    assert updated["root_run_id"] == previous["root_run_id"]


def test_generator_none_degrades_to_fallback_without_spending() -> None:
    approach, spent = generate_approach_or_fallback(
        None, mode="standard", query="比较开源编辑器"
    )
    assert approach["origin"] == "fallback"
    assert approach["status"] == "ready"
    assert spent is False


def test_generator_success_marks_model_generated() -> None:
    def completion(messages, **kwargs):  # noqa: ANN001
        assert kwargs["response_format"] == "json_object"
        return json.dumps(
            {"summary": "我会先核对官方说明，再比较自动化接口。", "focus": ["官方说明", "自动化"]},
            ensure_ascii=False,
        )

    approach, spent = generate_approach_or_fallback(
        completion, mode="standard", query="比较开源编辑器"
    )
    assert approach["origin"] == "model_generated"
    assert approach["status"] == "ready"
    assert spent is True
    assert approach["focus"] == ["官方说明", "自动化"]
    _assert_no_authority(approach)


def test_generator_exception_fails_open() -> None:
    def completion(messages, **kwargs):  # noqa: ANN001
        raise TimeoutError("provider timeout")

    approach, spent = generate_approach_or_fallback(
        completion, mode="deep", query="PS 开源替代"
    )
    assert approach["origin"] == "fallback"
    assert spent is True


def test_generator_invalid_payload_fails_open() -> None:
    def completion(messages, **kwargs):  # noqa: ANN001
        return "not json"

    approach, _ = generate_approach_or_fallback(
        completion, mode="standard", query="x"
    )
    assert approach["origin"] == "fallback"


def test_generate_approach_rejects_claiming_payload() -> None:
    def completion(messages, **kwargs):  # noqa: ANN001
        return json.dumps({"summary": "已完成核验并给出结论。", "focus": []}, ensure_ascii=False)

    with pytest.raises(ValueError):
        generate_approach(completion, mode="standard", query="x")


def test_approach_event_binds_run_identity_and_omits_authority() -> None:
    approach = project_from_plan(mode="standard", summary="我会比较功能覆盖与兼容性。")
    event = approach_event(approach, root_run_id="research_123", turn_id="turn_456")
    assert event is not None
    assert event["root_run_id"] == "research_123"
    assert event["turn_id"] == "turn_456"
    assert event["summary"] == "我会比较功能覆盖与兼容性。"
    assert event["mode"] == "standard"
    _assert_no_authority(event)


def test_approach_event_none_for_invalid_input() -> None:
    assert approach_event(None) is None
    assert approach_event({"schema": "wrong"}) is None


def test_fallback_is_honest_and_authority_free() -> None:
    approach = fallback_approach(mode="lookup")
    assert approach["origin"] == "fallback"
    assert approach["status"] == "ready"
    _assert_no_authority(approach)
