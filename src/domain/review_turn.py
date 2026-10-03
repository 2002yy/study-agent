"""Server-owned review binding persisted in existing ChatTurn snapshots."""

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from typing import Any


def review_time(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


@dataclass(frozen=True)
class ReviewTurnBinding:
    thread_id: str
    goal_id: str
    claim_revision_id: str
    last_validated_at: str
    prompt_turn_id: str
    question: str
    claim_text: str
    objective: str
    evidence_ids: tuple[str, ...]
    method: str = "explain"
    schema_version: str = "review-turn-v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> "ReviewTurnBinding":
        names = {item.name for item in fields(cls)}
        if not isinstance(value, dict) or set(value) != names:
            raise ValueError("Invalid review binding fields")
        if value["schema_version"] != "review-turn-v1" or value["method"] != "explain":
            raise ValueError("Unsupported review binding")
        for name in names - {"evidence_ids"}:
            if not isinstance(value[name], str) or not value[name].strip():
                raise ValueError("Invalid review binding value")
        refs = value["evidence_ids"]
        if (
            not isinstance(refs, (list, tuple))
            or not refs
            or any(not isinstance(ref, str) or not ref for ref in refs)
        ):
            raise ValueError("Review requires pinned revision evidence")
        review_time(value["last_validated_at"])
        return cls(**{**value, "evidence_ids": tuple(refs)})

    def snapshot(self, phase: str) -> dict[str, Any]:
        if phase not in {"prompt", "answer"}:
            raise ValueError("Invalid review phase")
        return {"phase": phase, "binding": self.to_dict()}


def read_review_snapshot(value: object, *, phase: str) -> ReviewTurnBinding:
    if not isinstance(value, dict) or set(value) != {"phase", "binding"}:
        raise ValueError("Invalid persisted review snapshot")
    if value["phase"] != phase:
        raise ValueError("Review phase mismatch")
    return ReviewTurnBinding.from_dict(value["binding"])
