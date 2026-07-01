from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

KnowledgeKind = Literal[
    "derivable",
    "empirical",
    "conventional",
    "procedural",
    "diagnostic",
]

PedagogicalMove = Literal[
    "elicit_claim",
    "clarify_definition",
    "expose_assumption",
    "request_prediction",
    "test_example",
    "offer_counterexample",
    "surface_contradiction",
    "give_hint",
    "provide_library_fact",
    "reconstruct",
    "transfer",
    "direct_explain",
    "set_scope",
    "invite_explanation",
    "identify_main_gap",
    "minimal_repair",
    "request_reexplanation",
    "transfer_test",
    "define_acceptance",
    "inspect_artifact",
    "form_hypothesis",
    "choose_solution",
    "apply_patch",
    "run_validation",
    "close_stage",
]


@dataclass(frozen=True)
class LearningState:
    protocol: str = ""
    protocol_version: int = 2
    objective: str = ""
    phase: str = "orientation"
    learner_claim: str = ""
    confirmed_points: tuple[str, ...] = ()
    unresolved_gap: str = ""
    attempted_examples: tuple[str, ...] = ()
    hint_level: int = 0
    library_facts_given: tuple[str, ...] = ()
    turn_count: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    suspended: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "LearningState":
        data = value or {}
        return cls(
            protocol=str(data.get("protocol", "")),
            protocol_version=max(1, int(data.get("protocol_version", 1) or 1)),
            objective=str(data.get("objective", "")),
            phase=str(data.get("phase", "orientation")),
            learner_claim=str(data.get("learner_claim", "")),
            confirmed_points=tuple(data.get("confirmed_points") or ()),
            unresolved_gap=str(data.get("unresolved_gap", "")),
            attempted_examples=tuple(data.get("attempted_examples") or ()),
            hint_level=max(0, min(5, int(data.get("hint_level", 0) or 0))),
            library_facts_given=tuple(data.get("library_facts_given") or ()),
            turn_count=max(0, int(data.get("turn_count", 0) or 0)),
            payload=dict(data.get("payload") or {}),
            suspended={
                str(key): dict(item)
                for key, item in dict(data.get("suspended") or {}).items()
                if isinstance(item, dict)
            },
        )


PedagogyState = LearningState


@dataclass(frozen=True)
class LearnerResponseEvaluation:
    passed: bool
    is_claim: bool
    reason: str
    misconceptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssistantResponseEvaluation:
    passed: bool
    violations: tuple[str, ...] = ()
    question_count: int = 0


@dataclass(frozen=True)
class PedagogyTurnPlan:
    mode: str
    phase: str
    knowledge_kind: KnowledgeKind
    move: PedagogicalMove
    disclosure_level: int
    learner_claim: str = ""
    unresolved_gap: str = ""
    target_understanding: str = ""
    library_needed: bool = False
    evidence_ids: tuple[str, ...] = ()
    constraints: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
