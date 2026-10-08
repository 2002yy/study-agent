"""Learning State-1 L1 tests: read-only authority projection + consumer rule.

Covers contract §2 (L1) and §9 (T01–T06). The integration tests are the
mutation-sensitive ones: restoring the legacy ``confirmed_points`` fallback in
``chat_service.py`` / ``policy_chat_service.py`` makes them fail (M1), and
treating a legacy point as verified would fail the projection tests (M2).
"""

from __future__ import annotations

from src.application.chat_service import ChatCommand, ChatDependencies, ChatService
from src.application.learning_authority_projection import (
    AUTHORITY_LEGACY_UNVERIFIED,
    AUTHORITY_SYSTEM_INFERRED,
    AUTHORITY_USER_GOAL,
    AUTHORITY_VERIFIED,
    LearningAuthorityItem,
    classify_durable_understanding_status,
    classify_expected_concept,
    classify_legacy_confirmed_points,
    is_mastery_authority,
    resolve_expected_concepts,
)
from src.domain.runtime_entities import ChatThread
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.mode_manager import RuntimeModes
from src.pedagogy.evaluation import PedagogyEvaluationService
from src.repositories.runtime_repository import RuntimeRepository
from src.tools.web_agent import WebToolTrace


# --- pure projection tests (T01/T03, M2) -----------------------------------

def test_legacy_confirmed_points_are_never_verified():
    items = classify_legacy_confirmed_points(["所以 Java 参数是引用传递", "我明白了"])
    assert items, "expected at least one item"
    assert {item.authority for item in items} == {AUTHORITY_LEGACY_UNVERIFIED}
    assert all(item.is_mastery_evidence is False for item in items)
    # No invented source id.
    assert all(item.source_id == "" for item in items)


def test_only_durable_confirmed_is_mastery():
    confirmed = classify_durable_understanding_status("confirmed", text="X")
    assert confirmed.authority == AUTHORITY_VERIFIED
    assert confirmed.is_mastery_evidence is True

    for status in ("partial", "attempted", "proposed", "none", ""):
        item = classify_durable_understanding_status(status, text="X")
        assert item.authority == AUTHORITY_SYSTEM_INFERRED, status
        assert item.is_mastery_evidence is False, status


def test_is_mastery_authority_only_verified():
    assert is_mastery_authority(AUTHORITY_VERIFIED) is True
    for authority in (
        AUTHORITY_USER_GOAL,
        AUTHORITY_SYSTEM_INFERRED,
        AUTHORITY_LEGACY_UNVERIFIED,
        "user_self_report",
    ):
        assert is_mastery_authority(authority) is False


def test_expected_concept_is_never_mastery():
    item = classify_expected_concept("理解引用类型")
    assert item.authority == AUTHORITY_USER_GOAL
    assert item.is_mastery_evidence is False


def test_resolve_expected_concepts_never_uses_legacy_confirmed_points():
    # §2.4: no explicit curriculum target -> empty, never a legacy fallback.
    assert resolve_expected_concepts({}) == ()
    assert resolve_expected_concepts(None) == ()
    assert resolve_expected_concepts({"confirmed_points": ["我懂了"]}) == ()


def test_resolve_expected_concepts_reads_explicit_targets_only():
    assert resolve_expected_concepts({"expected_concepts": ["A", "B"]}) == ("A", "B")
    assert resolve_expected_concepts({"expected_concepts": "A"}) == ("A",)
    # Malformed values are ignored conservatively, not split.
    assert resolve_expected_concepts({"expected_concepts": 3}) == ()
    assert resolve_expected_concepts({"expected_concepts": ["", "  "]}) == ()
    assert resolve_expected_concepts({"expected_concepts": [" A ", 5]}) == ("A", "5")


def test_item_to_dict_exposes_mastery_flag():
    item = LearningAuthorityItem(kind="claim", authority=AUTHORITY_LEGACY_UNVERIFIED)
    payload = item.to_dict()
    assert payload["is_mastery_evidence"] is False
    assert payload["authority"] == AUTHORITY_LEGACY_UNVERIFIED


# --- integration tests through ChatService (T04/T05, M1) -------------------

class FakeRagResult:
    context = "local context"

    def to_dict(self):
        return {
            "status": "found",
            "context": self.context,
            "result_count": 1,
            "results": [],
        }


class RecordingEvaluation:
    """Wrap the real evaluation service, recording expected_concepts."""

    def __init__(self) -> None:
        self.expected: list[tuple[str, ...]] = []
        self._real = PedagogyEvaluationService()

    def evaluate_learner(self, **kwargs):
        self.expected.append(tuple(kwargs.get("expected_concepts") or ()))
        return self._real.evaluate_learner(**kwargs)


def _service(tmp_path, evaluation) -> tuple[ChatService, RuntimeRepository]:
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    dependencies = ChatDependencies(
        load_runtime_modes=lambda: RuntimeModes(
            memory_mode="preview",
            performance_mode="standard",
        ),
        read_memory_bundle=lambda context_mode: {},
        build_role_prompt=lambda role, **kwargs: f"role:{role}",
        route_request=lambda **kwargs: {
            "role": "nahida",
            "mode": "普通",
            "model_profile": "flash",
            "reason": "test",
        },
        retrieve_local_knowledge=lambda *args, **kwargs: FakeRagResult(),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs["role_prompt"]},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        chat=lambda *args, **kwargs: "complete reply",
        stream_chat=lambda *args, **kwargs: iter(["part"]),
        chat_max_tokens=lambda performance_mode: 1000,
        resolve_web_tools=lambda *args, **kwargs: WebToolTrace(enabled=False),
        pedagogy_evaluation=evaluation,
    )
    return ChatService(repository, dependencies), repository


def test_expected_concepts_do_not_fall_back_to_confirmed_points(tmp_path):
    evaluation = RecordingEvaluation()
    service, repository = _service(tmp_path, evaluation)
    repository.create_chat_thread(
        ChatThread(
            id="thread_legacy",
            learning_state={
                "objective": "理解引用类型",
                "confirmed_points": ["所以我明白了，Java 参数都是引用传递"],
            },
        )
    )

    service.start_turn(ChatCommand(user_input="我继续", thread_id="thread_legacy"))

    assert evaluation.expected, "evaluation was not called"
    assert evaluation.expected[-1] == (), (
        "legacy confirmed_points must not become expected_concepts"
    )


def test_explicit_expected_concepts_are_passed_through(tmp_path):
    evaluation = RecordingEvaluation()
    service, repository = _service(tmp_path, evaluation)
    repository.create_chat_thread(
        ChatThread(
            id="thread_target",
            learning_state={
                "objective": "理解引用类型",
                "confirmed_points": ["我懂了"],
                "payload": {"expected_concepts": ["引用传递", "值传递"]},
            },
        )
    )

    service.start_turn(ChatCommand(user_input="我继续", thread_id="thread_target"))

    assert evaluation.expected[-1] == ("引用传递", "值传递")
