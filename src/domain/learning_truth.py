"""Durable learning-truth domain types for P2-D.

These objects are deliberately small. They represent committed learning truth and
navigation state, not retrieval diagnostics, LLM confidence, or display caches.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.domain.runtime_entities import new_id, utc_now


@dataclass(frozen=True)
class LearningTopic:
    id: str = field(default_factory=lambda: new_id("topic"))
    title: str = ""
    scope: str = "project"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class LearningGoal:
    id: str = field(default_factory=lambda: new_id("goal"))
    topic_id: str = ""
    objective: str = ""
    status: str = "active"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class LearningGoalContext:
    goal_id: str
    thread_id: str
    focused_at: str
    focus_pinned: bool = False


@dataclass(frozen=True)
class LearningClaim:
    id: str = field(default_factory=lambda: new_id("claim"))
    topic_id: str = ""
    scope: str = "project"
    claim_kind: str = "mechanism"
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class ClaimRevision:
    id: str = field(default_factory=lambda: new_id("claim_rev"))
    claim_id: str = ""
    claim_text: str = ""
    source_commit: str = ""
    reason: str = "initial"
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class SourceEvidence:
    id: str = field(default_factory=lambda: new_id("source_ev"))
    repository: str = ""
    commit_sha: str = ""
    tree_sha: str = ""
    path: str = ""
    file_sha: str = ""
    symbol: str = ""
    symbol_kind: str = ""
    start_line: int = 1
    end_line: int = 1
    evidence_kind: str = "source"
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class EvidenceBinding:
    source: SourceEvidence
    role: str
    position: int


@dataclass(frozen=True)
class ClaimRevisionBundle:
    revision: ClaimRevision
    evidence: tuple[EvidenceBinding, ...] = ()


@dataclass(frozen=True)
class UnderstandingEvidence:
    id: str = field(default_factory=lambda: new_id("understanding"))
    method: str = "explain"
    prompt: str = ""
    user_response: str = ""
    verified_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class UnderstandingClaimResult:
    understanding_evidence_id: str
    claim_revision_id: str
    result: str


@dataclass(frozen=True)
class LearningHypothesis:
    id: str = field(default_factory=lambda: new_id("hypothesis"))
    topic_id: str = ""
    goal_id: str = ""
    text: str = ""
    unresolved_reason: str = "insufficient_evidence"
    resolved_by_claim_id: str | None = None
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class NextStep:
    id: str = field(default_factory=lambda: new_id("next_step"))
    goal_id: str = ""
    text: str = ""
    status: str = "active"
    is_primary: bool = False
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class LearnerMisconception:
    """168: durable misconception. An observation is not this; see 168.2."""

    id: str = field(default_factory=lambda: new_id("misconception"))
    goal_id: str = ""
    description: str = ""
    status: str = "suspected"
    occurrence_count: int = 1
    source_eval_ref: str = ""
    first_seen_at: str = field(default_factory=utc_now)
    last_seen_at: str = field(default_factory=utc_now)
