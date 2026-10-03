"""Single SQLite transaction owner for durable P2-D learning truth."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from src.domain.learning_truth import (
    ClaimRevision,
    ClaimRevisionBundle,
    EvidenceBinding,
    LearningClaim,
    LearningGoal,
    LearningGoalContext,
    LearningHypothesis,
    LearnerMisconception,
    LearningTopic,
    NextStep,
    SourceEvidence,
    UnderstandingClaimResult,
    UnderstandingEvidence,
)
from src.domain.runtime_entities import utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase


_ALLOWED_EVIDENCE_ROLES = {
    "primary",
    "supporting_corroborating",
    "supporting_prerequisite",
}
_ALLOWED_UNDERSTANDING_RESULTS = {"pass", "partial", "fail"}
_ALLOWED_GOAL_STATUSES = {"active", "blocked", "completed", "abandoned"}
_TERMINAL_GOAL_STATUSES = {"completed", "abandoned"}


class LearningTruthRepository:
    """Own normalized durable learning truth and its transaction boundaries."""

    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()

    def create_topic(self, topic: LearningTopic) -> LearningTopic:
        if not topic.title.strip():
            raise ValueError("Learning topic title is required")
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO learning_topics(id, title, scope, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (topic.id, topic.title, topic.scope, topic.created_at, topic.updated_at),
            )
        return topic

    def get_topic(self, topic_id: str) -> LearningTopic | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM learning_topics WHERE id = ?", (topic_id,)
            ).fetchone()
        return _topic_from_row(row) if row else None

    def list_topics(self) -> list[LearningTopic]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM learning_topics ORDER BY updated_at DESC, id"
            ).fetchall()
        return [_topic_from_row(row) for row in rows]

    def create_goal(self, goal: LearningGoal) -> LearningGoal:
        self._validate_goal(goal)
        with self.database.connect() as connection:
            self._require_topic(connection, goal.topic_id)
            self._insert_goal(connection, goal)
        return goal

    def create_goal_for_thread(
        self,
        goal: LearningGoal,
        *,
        thread_id: str,
        focus_pinned: bool = False,
    ) -> tuple[LearningGoal, LearningGoalContext]:
        """Atomically create a Goal and bind its navigation context to a ChatThread."""

        self._validate_goal(goal)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._require_topic(connection, goal.topic_id)
                self._require_thread(connection, thread_id)
                self._insert_goal(connection, goal)
                if focus_pinned:
                    self._unpin_thread_goals(connection, thread_id)
                context = LearningGoalContext(
                    goal_id=goal.id,
                    thread_id=thread_id,
                    focused_at=goal.updated_at,
                    focus_pinned=focus_pinned,
                )
                self._insert_goal_context(connection, context)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return goal, context

    def bind_goal_context(
        self,
        goal_id: str,
        *,
        thread_id: str,
        focus_pinned: bool = False,
        focused_at: str | None = None,
    ) -> LearningGoalContext:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._require_goal(connection, goal_id)
                self._require_thread(connection, thread_id)
                existing = connection.execute(
                    "SELECT * FROM learning_goal_contexts WHERE goal_id = ?",
                    (goal_id,),
                ).fetchone()
                if existing is not None and str(existing["thread_id"]) != thread_id:
                    raise ValueError("Learning Goal is already bound to another thread")
                if focus_pinned:
                    self._unpin_thread_goals(connection, thread_id, except_goal_id=goal_id)
                context = LearningGoalContext(
                    goal_id=goal_id,
                    thread_id=thread_id,
                    focused_at=focused_at or utc_now(),
                    focus_pinned=focus_pinned,
                )
                if existing is None:
                    self._insert_goal_context(connection, context)
                else:
                    connection.execute(
                        """
                        UPDATE learning_goal_contexts
                        SET focused_at = ?, focus_pinned = ?
                        WHERE goal_id = ?
                        """,
                        (context.focused_at, int(context.focus_pinned), goal_id),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return context

    def get_goal_context(self, goal_id: str) -> LearningGoalContext | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM learning_goal_contexts WHERE goal_id = ?",
                (goal_id,),
            ).fetchone()
        return _goal_context_from_row(row) if row else None

    def focus_goal(
        self,
        goal_id: str,
        *,
        pinned: bool | None = None,
    ) -> LearningGoalContext:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                goal = self._require_goal(connection, goal_id)
                if str(goal["status"]) not in {"active", "blocked"}:
                    raise ValueError("Only active or blocked Goals can become current focus")
                row = connection.execute(
                    "SELECT * FROM learning_goal_contexts WHERE goal_id = ?",
                    (goal_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Learning Goal has no thread context: {goal_id}")
                thread_id = str(row["thread_id"])
                next_pinned = bool(row["focus_pinned"]) if pinned is None else pinned
                if next_pinned:
                    self._unpin_thread_goals(connection, thread_id, except_goal_id=goal_id)
                focused_at = utc_now()
                connection.execute(
                    """
                    UPDATE learning_goal_contexts
                    SET focused_at = ?, focus_pinned = ?
                    WHERE goal_id = ?
                    """,
                    (focused_at, int(next_pinned), goal_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return LearningGoalContext(
            goal_id=goal_id,
            thread_id=thread_id,
            focused_at=focused_at,
            focus_pinned=next_pinned,
        )

    def get_focus_goal(self, thread_id: str) -> LearningGoal | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT goal.*
                FROM learning_goals AS goal
                JOIN learning_goal_contexts AS context ON context.goal_id = goal.id
                WHERE context.thread_id = ?
                  AND goal.status IN ('active', 'blocked')
                ORDER BY context.focus_pinned DESC,
                         context.focused_at DESC,
                         goal.updated_at DESC,
                         goal.id
                LIMIT 1
                """,
                (thread_id,),
            ).fetchone()
        return _goal_from_row(row) if row else None

    def list_goals_for_thread(self, thread_id: str) -> list[LearningGoal]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT goal.*
                FROM learning_goals AS goal
                JOIN learning_goal_contexts AS context ON context.goal_id = goal.id
                WHERE context.thread_id = ?
                ORDER BY context.focus_pinned DESC,
                         context.focused_at DESC,
                         goal.updated_at DESC,
                         goal.id
                """,
                (thread_id,),
            ).fetchall()
        return [_goal_from_row(row) for row in rows]

    def update_goal_status(self, goal_id: str, status: str) -> LearningGoal:
        if status not in _ALLOWED_GOAL_STATUSES:
            raise ValueError("Unsupported Learning Goal status")
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._require_goal(connection, goal_id)
                connection.execute(
                    "UPDATE learning_goals SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now, goal_id),
                )
                if status in _TERMINAL_GOAL_STATUSES:
                    connection.execute(
                        """
                        UPDATE learning_goal_contexts
                        SET focus_pinned = 0
                        WHERE goal_id = ?
                        """,
                        (goal_id,),
                    )
                row = self._require_goal(connection, goal_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return _goal_from_row(row)

    def get_goal(self, goal_id: str) -> LearningGoal | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM learning_goals WHERE id = ?", (goal_id,)
            ).fetchone()
        return _goal_from_row(row) if row else None

    def list_goals(self, topic_id: str) -> list[LearningGoal]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM learning_goals
                WHERE topic_id = ? ORDER BY updated_at DESC, id
                """,
                (topic_id,),
            ).fetchall()
        return [_goal_from_row(row) for row in rows]

    def add_prerequisite(self, goal_id: str, prerequisite_goal_id: str) -> None:
        if goal_id == prerequisite_goal_id:
            raise ValueError("Learning goal cannot require itself")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._require_goal(connection, goal_id)
                self._require_goal(connection, prerequisite_goal_id)
                if self._would_create_prerequisite_cycle(
                    connection,
                    goal_id=goal_id,
                    prerequisite_goal_id=prerequisite_goal_id,
                ):
                    raise ValueError("Learning goal prerequisite cycle detected")
                connection.execute(
                    """
                    INSERT INTO learning_goal_prerequisites(goal_id, prerequisite_goal_id)
                    VALUES (?, ?)
                    """,
                    (goal_id, prerequisite_goal_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def list_prerequisite_ids(self, goal_id: str) -> list[str]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT prerequisite_goal_id
                FROM learning_goal_prerequisites
                WHERE goal_id = ? ORDER BY prerequisite_goal_id
                """,
                (goal_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def create_claim(self, claim: LearningClaim) -> LearningClaim:
        with self.database.connect() as connection:
            self._require_topic(connection, claim.topic_id)
            self._insert_claim(connection, claim)
        return claim

    def commit_new_claim(
        self,
        claim: LearningClaim,
        revision: ClaimRevision,
        bindings: Sequence[EvidenceBinding],
        *,
        goal_id: str | None = None,
    ) -> ClaimRevisionBundle:
        """Atomically create a Claim together with its first immutable Revision."""

        normalized = tuple(bindings)
        self._validate_revision_bindings(normalized)
        self._validate_revision_text(revision)
        if revision.claim_id != claim.id:
            raise ValueError("Claim revision owner does not match new claim id")
        if revision.reason != "initial":
            raise ValueError("New learning claim must start with an initial revision")

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._require_topic(connection, claim.topic_id)
                if goal_id is not None:
                    goal = self._require_goal(connection, goal_id)
                    if str(goal["topic_id"]) != claim.topic_id:
                        raise ValueError("Learning Claim Goal belongs to another topic")
                self._insert_claim(connection, claim)
                bundle = self._insert_revision_bundle(
                    connection,
                    revision,
                    normalized,
                    goal_id=goal_id,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return bundle

    def get_claim(self, claim_id: str) -> LearningClaim | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM learning_claims WHERE id = ?", (claim_id,)
            ).fetchone()
        return _claim_from_row(row) if row else None

    def list_claims(self, topic_id: str) -> list[LearningClaim]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM learning_claims
                WHERE topic_id = ? ORDER BY created_at, id
                """,
                (topic_id,),
            ).fetchall()
        return [_claim_from_row(row) for row in rows]

    def commit_revision(
        self,
        revision: ClaimRevision,
        bindings: Sequence[EvidenceBinding],
        *,
        goal_id: str | None = None,
    ) -> ClaimRevisionBundle:
        normalized = tuple(bindings)
        self._validate_revision_bindings(normalized)
        self._validate_revision_text(revision)

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                claim = self._require_claim(connection, revision.claim_id)
                if goal_id is not None:
                    goal = self._require_goal(connection, goal_id)
                    if str(goal["topic_id"]) != str(claim["topic_id"]):
                        raise ValueError("Learning Claim Goal belongs to another topic")
                bundle = self._insert_revision_bundle(
                    connection,
                    revision,
                    normalized,
                    goal_id=goal_id,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return bundle

    def get_revision(self, revision_id: str) -> ClaimRevisionBundle | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM claim_revisions WHERE id = ?", (revision_id,)
            ).fetchone()
            if row is None:
                return None
            evidence_rows = connection.execute(
                """
                SELECT e.*, link.role, link.position
                FROM claim_revision_evidence AS link
                JOIN source_evidence AS e ON e.id = link.source_evidence_id
                WHERE link.claim_revision_id = ?
                ORDER BY link.position, e.id
                """,
                (revision_id,),
            ).fetchall()
        return ClaimRevisionBundle(
            revision=_revision_from_row(row),
            evidence=tuple(
                EvidenceBinding(
                    source=_source_evidence_from_row(item),
                    role=str(item["role"]),
                    position=int(item["position"]),
                )
                for item in evidence_rows
            ),
        )

    def list_revisions(self, claim_id: str) -> list[ClaimRevisionBundle]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id FROM claim_revisions
                WHERE claim_id = ? ORDER BY created_at, id
                """,
                (claim_id,),
            ).fetchall()
        result: list[ClaimRevisionBundle] = []
        for row in rows:
            bundle = self.get_revision(str(row["id"]))
            if bundle is not None:
                result.append(bundle)
        return result

    def list_goal_revisions(self, goal_id: str) -> list[ClaimRevisionBundle]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT relation.claim_revision_id
                FROM learning_goal_claim_revisions AS relation
                JOIN claim_revisions AS revision
                  ON revision.id = relation.claim_revision_id
                WHERE relation.goal_id = ?
                ORDER BY relation.created_at, revision.created_at, revision.id
                """,
                (goal_id,),
            ).fetchall()
        result: list[ClaimRevisionBundle] = []
        for row in rows:
            bundle = self.get_revision(str(row["claim_revision_id"]))
            if bundle is not None:
                result.append(bundle)
        return result

    def create_understanding_evidence(
        self,
        evidence: UnderstandingEvidence,
        results: Sequence[UnderstandingClaimResult],
    ) -> UnderstandingEvidence:
        normalized = tuple(results)
        self._validate_understanding_results(evidence, normalized)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for item in normalized:
                    self._require_revision(connection, item.claim_revision_id)
                self._insert_understanding(connection, evidence, normalized)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return evidence

    def commit_semantic_closure(
        self,
        *,
        goal_id: str,
        understanding: UnderstandingEvidence | None = None,
        results: Sequence[UnderstandingClaimResult] = (),
        goal_status: str | None = None,
        next_step: NextStep | None = None,
    ) -> tuple[UnderstandingEvidence | None, NextStep | None, LearningGoal]:
        """Atomically record a validation attempt and the resulting Goal navigation state."""

        normalized = tuple(results)
        if understanding is None and normalized:
            raise ValueError("Understanding results require UnderstandingEvidence")
        if understanding is not None:
            self._validate_understanding_results(understanding, normalized)
        if goal_status is not None and goal_status not in _ALLOWED_GOAL_STATUSES:
            raise ValueError("Unsupported Learning Goal status")
        if next_step is not None and next_step.goal_id != goal_id:
            raise ValueError("NextStep owner does not match semantic closure Goal")
        if next_step is not None and goal_status in _TERMINAL_GOAL_STATUSES:
            raise ValueError("Terminal Learning Goal cannot create an active NextStep")

        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._require_goal(connection, goal_id)
                if understanding is not None:
                    for item in normalized:
                        self._require_revision(connection, item.claim_revision_id)
                        relation = connection.execute(
                            """
                            SELECT 1 FROM learning_goal_claim_revisions
                            WHERE goal_id = ? AND claim_revision_id = ?
                            """,
                            (goal_id, item.claim_revision_id),
                        ).fetchone()
                        if relation is None:
                            raise ValueError(
                                "UnderstandingEvidence can only validate revisions linked to its Goal"
                            )
                    self._insert_understanding(connection, understanding, normalized)
                if goal_status is not None:
                    connection.execute(
                        "UPDATE learning_goals SET status = ?, updated_at = ? WHERE id = ?",
                        (goal_status, now, goal_id),
                    )
                if goal_status in _TERMINAL_GOAL_STATUSES:
                    connection.execute(
                        "UPDATE learning_goal_contexts SET focus_pinned = 0 WHERE goal_id = ?",
                        (goal_id,),
                    )
                else:
                    connection.execute(
                        "UPDATE learning_goal_contexts SET focused_at = ? WHERE goal_id = ?",
                        (now, goal_id),
                    )
                if next_step is not None:
                    self._insert_next_step(connection, next_step)
                goal_row = self._require_goal(connection, goal_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return understanding, next_step, _goal_from_row(goal_row)

    def get_understanding_evidence(
        self, evidence_id: str
    ) -> tuple[UnderstandingEvidence, tuple[UnderstandingClaimResult, ...]] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM understanding_evidence WHERE id = ?", (evidence_id,)
            ).fetchone()
            if row is None:
                return None
            result_rows = connection.execute(
                """
                SELECT * FROM understanding_evidence_claims
                WHERE understanding_evidence_id = ? ORDER BY claim_revision_id
                """,
                (evidence_id,),
            ).fetchall()
        evidence = _understanding_from_row(row)
        return evidence, tuple(
            UnderstandingClaimResult(
                understanding_evidence_id=str(item["understanding_evidence_id"]),
                claim_revision_id=str(item["claim_revision_id"]),
                result=str(item["result"]),
            )
            for item in result_rows
        )

    def list_understanding_for_revision(
        self,
        revision_id: str,
    ) -> list[tuple[UnderstandingEvidence, UnderstandingClaimResult]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT evidence.*, relation.result
                FROM understanding_evidence_claims AS relation
                JOIN understanding_evidence AS evidence
                  ON evidence.id = relation.understanding_evidence_id
                WHERE relation.claim_revision_id = ?
                ORDER BY evidence.verified_at, evidence.id
                """,
                (revision_id,),
            ).fetchall()
        return [
            (
                _understanding_from_row(row),
                UnderstandingClaimResult(
                    understanding_evidence_id=str(row["id"]),
                    claim_revision_id=revision_id,
                    result=str(row["result"]),
                ),
            )
            for row in rows
        ]

    def create_hypothesis(self, hypothesis: LearningHypothesis) -> LearningHypothesis:
        if not hypothesis.text.strip():
            raise ValueError("Learning hypothesis text is required")
        with self.database.connect() as connection:
            self._require_topic(connection, hypothesis.topic_id)
            goal = self._require_goal(connection, hypothesis.goal_id)
            if str(goal["topic_id"]) != hypothesis.topic_id:
                raise ValueError("Learning hypothesis goal belongs to another topic")
            connection.execute(
                """
                INSERT INTO learning_hypotheses(
                    id, topic_id, goal_id, text, unresolved_reason,
                    resolved_by_claim_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hypothesis.id,
                    hypothesis.topic_id,
                    hypothesis.goal_id,
                    hypothesis.text,
                    hypothesis.unresolved_reason,
                    hypothesis.resolved_by_claim_id,
                    hypothesis.created_at,
                ),
            )
        return hypothesis

    def get_hypothesis(self, hypothesis_id: str) -> LearningHypothesis | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM learning_hypotheses WHERE id = ?", (hypothesis_id,)
            ).fetchone()
        return _hypothesis_from_row(row) if row else None

    def list_hypotheses_for_goal(self, goal_id: str) -> list[LearningHypothesis]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM learning_hypotheses
                WHERE goal_id = ? ORDER BY created_at, id
                """,
                (goal_id,),
            ).fetchall()
        return [_hypothesis_from_row(row) for row in rows]

    def create_next_step(self, next_step: NextStep) -> NextStep:
        if not next_step.text.strip():
            raise ValueError("Next step text is required")
        with self.database.connect() as connection:
            self._require_goal(connection, next_step.goal_id)
            self._insert_next_step(connection, next_step)
        return next_step

    def get_next_step(self, next_step_id: str) -> NextStep | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM next_steps WHERE id = ?", (next_step_id,)
            ).fetchone()
        return _next_step_from_row(row) if row else None

    def list_next_steps_for_goal(self, goal_id: str) -> list[NextStep]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM next_steps
                WHERE goal_id = ?
                ORDER BY is_primary DESC, updated_at DESC, id
                """,
                (goal_id,),
            ).fetchall()
        return [_next_step_from_row(row) for row in rows]

    def create_misconception(
        self, item: LearnerMisconception
    ) -> LearnerMisconception:
        if not item.description.strip():
            raise ValueError("Misconception description is required")
        with self.database.connect() as connection:
            self._require_goal(connection, item.goal_id)
            self._insert_misconception(connection, item)
        return item

    def get_misconception(
        self, misconception_id: str
    ) -> LearnerMisconception | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM learner_misconceptions WHERE id = ?",
                (misconception_id,),
            ).fetchone()
        return _misconception_from_row(row) if row else None

    def list_misconceptions_for_goal(
        self, goal_id: str
    ) -> list[LearnerMisconception]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM learner_misconceptions
                WHERE goal_id = ?
                ORDER BY last_seen_at DESC, id
                """,
                (goal_id,),
            ).fetchall()
        return [_misconception_from_row(row) for row in rows]

    def update_misconception(
        self, item: LearnerMisconception
    ) -> LearnerMisconception:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE learner_misconceptions
                SET description = ?, status = ?, occurrence_count = ?,
                    source_eval_ref = ?, last_seen_at = ?
                WHERE id = ?
                """,
                (
                    item.description,
                    item.status,
                    item.occurrence_count,
                    item.source_eval_ref,
                    item.last_seen_at,
                    item.id,
                ),
            )
        return item

    def find_misconception_by_description(
        self, goal_id: str, description: str
    ) -> LearnerMisconception | None:
        target = description.strip().lower()
        return next(
            (
                item
                for item in self.list_misconceptions_for_goal(goal_id)
                if item.description.strip().lower() == target
            ),
            None,
        )

    @staticmethod
    def _validate_goal(goal: LearningGoal) -> None:
        if not goal.objective.strip():
            raise ValueError("Learning goal objective is required")
        if goal.status not in _ALLOWED_GOAL_STATUSES:
            raise ValueError("Unsupported Learning Goal status")

    @staticmethod
    def _insert_goal(connection: sqlite3.Connection, goal: LearningGoal) -> None:
        connection.execute(
            """
            INSERT INTO learning_goals(
                id, topic_id, objective, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                goal.id,
                goal.topic_id,
                goal.objective,
                goal.status,
                goal.created_at,
                goal.updated_at,
            ),
        )

    @staticmethod
    def _insert_goal_context(
        connection: sqlite3.Connection,
        context: LearningGoalContext,
    ) -> None:
        connection.execute(
            """
            INSERT INTO learning_goal_contexts(
                goal_id, thread_id, focused_at, focus_pinned
            ) VALUES (?, ?, ?, ?)
            """,
            (
                context.goal_id,
                context.thread_id,
                context.focused_at,
                int(context.focus_pinned),
            ),
        )

    @staticmethod
    def _unpin_thread_goals(
        connection: sqlite3.Connection,
        thread_id: str,
        *,
        except_goal_id: str | None = None,
    ) -> None:
        if except_goal_id is None:
            connection.execute(
                "UPDATE learning_goal_contexts SET focus_pinned = 0 WHERE thread_id = ?",
                (thread_id,),
            )
        else:
            connection.execute(
                """
                UPDATE learning_goal_contexts
                SET focus_pinned = 0
                WHERE thread_id = ? AND goal_id <> ?
                """,
                (thread_id, except_goal_id),
            )

    @staticmethod
    def _insert_claim(connection: sqlite3.Connection, claim: LearningClaim) -> None:
        connection.execute(
            """
            INSERT INTO learning_claims(id, topic_id, scope, claim_kind, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                claim.id,
                claim.topic_id,
                claim.scope,
                claim.claim_kind,
                claim.created_at,
            ),
        )

    @classmethod
    def _insert_revision_bundle(
        cls,
        connection: sqlite3.Connection,
        revision: ClaimRevision,
        bindings: tuple[EvidenceBinding, ...],
        *,
        goal_id: str | None = None,
    ) -> ClaimRevisionBundle:
        connection.execute(
            """
            INSERT INTO claim_revisions(
                id, claim_id, claim_text, source_commit, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                revision.id,
                revision.claim_id,
                revision.claim_text,
                revision.source_commit,
                revision.reason,
                revision.created_at,
            ),
        )
        stored_bindings: list[EvidenceBinding] = []
        for binding in sorted(bindings, key=lambda item: item.position):
            stored_source = cls._store_or_reuse_source_evidence(connection, binding.source)
            connection.execute(
                """
                INSERT INTO claim_revision_evidence(
                    claim_revision_id, source_evidence_id, role, position
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    revision.id,
                    stored_source.id,
                    binding.role,
                    binding.position,
                ),
            )
            stored_bindings.append(
                EvidenceBinding(
                    source=stored_source,
                    role=binding.role,
                    position=binding.position,
                )
            )
        if goal_id is not None:
            connection.execute(
                """
                INSERT INTO learning_goal_claim_revisions(
                    goal_id, claim_revision_id, created_at
                ) VALUES (?, ?, ?)
                """,
                (goal_id, revision.id, revision.created_at),
            )
        return ClaimRevisionBundle(revision=revision, evidence=tuple(stored_bindings))

    @staticmethod
    def _validate_revision_text(revision: ClaimRevision) -> None:
        if not revision.claim_text.strip():
            raise ValueError("Claim revision text is required")

    @staticmethod
    def _validate_revision_bindings(bindings: tuple[EvidenceBinding, ...]) -> None:
        if not bindings:
            raise ValueError("Claim revision requires exactly one primary evidence")
        primary_count = sum(binding.role == "primary" for binding in bindings)
        supporting_count = len(bindings) - primary_count
        if primary_count != 1:
            raise ValueError("Claim revision requires exactly one primary evidence")
        if supporting_count > 4:
            raise ValueError("Claim revision supports at most four supporting evidence items")
        if any(binding.role not in _ALLOWED_EVIDENCE_ROLES for binding in bindings):
            raise ValueError("Unsupported claim evidence role")
        positions = [binding.position for binding in bindings]
        if any(position < 0 for position in positions) or len(set(positions)) != len(positions):
            raise ValueError("Claim evidence positions must be unique non-negative values")
        identities = [_source_identity(binding.source) for binding in bindings]
        if len(set(identities)) != len(identities):
            raise ValueError("Claim revision contains duplicate source evidence")
        for binding in bindings:
            _validate_source_evidence(binding.source)

    @staticmethod
    def _validate_understanding_results(
        evidence: UnderstandingEvidence,
        results: tuple[UnderstandingClaimResult, ...],
    ) -> None:
        if not 1 <= len(results) <= 3:
            raise ValueError("Understanding evidence must evaluate 1 to 3 claim revisions")
        if len({item.claim_revision_id for item in results}) != len(results):
            raise ValueError("Understanding evidence contains duplicate claim revisions")
        if any(item.understanding_evidence_id != evidence.id for item in results):
            raise ValueError("Understanding result owner does not match evidence id")
        if any(item.result not in _ALLOWED_UNDERSTANDING_RESULTS for item in results):
            raise ValueError("Unsupported understanding result")

    @staticmethod
    def _insert_understanding(
        connection: sqlite3.Connection,
        evidence: UnderstandingEvidence,
        results: tuple[UnderstandingClaimResult, ...],
    ) -> None:
        connection.execute(
            """
            INSERT INTO understanding_evidence(
                id, method, prompt, user_response, verified_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                evidence.id,
                evidence.method,
                evidence.prompt,
                evidence.user_response,
                evidence.verified_at,
            ),
        )
        connection.executemany(
            """
            INSERT INTO understanding_evidence_claims(
                understanding_evidence_id, claim_revision_id, result
            ) VALUES (?, ?, ?)
            """,
            [
                (evidence.id, item.claim_revision_id, item.result)
                for item in results
            ],
        )

    @staticmethod
    def _insert_next_step(connection: sqlite3.Connection, next_step: NextStep) -> None:
        if not next_step.text.strip():
            raise ValueError("Next step text is required")
        connection.execute(
            """
            INSERT INTO next_steps(
                id, goal_id, text, status, is_primary, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                next_step.id,
                next_step.goal_id,
                next_step.text,
                next_step.status,
                int(next_step.is_primary),
                next_step.created_at,
                next_step.updated_at,
            ),
        )

    @staticmethod
    def _insert_misconception(
        connection: sqlite3.Connection, item: LearnerMisconception
    ) -> None:
        if not item.description.strip():
            raise ValueError("Misconception description is required")
        connection.execute(
            """
            INSERT INTO learner_misconceptions(
                id, goal_id, description, status, occurrence_count,
                source_eval_ref, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.goal_id,
                item.description,
                item.status,
                item.occurrence_count,
                item.source_eval_ref,
                item.first_seen_at,
                item.last_seen_at,
            ),
        )

    @staticmethod
    def _store_or_reuse_source_evidence(
        connection: sqlite3.Connection,
        source: SourceEvidence,
    ) -> SourceEvidence:
        identity = _source_identity(source)
        row = connection.execute(
            """
            SELECT * FROM source_evidence
            WHERE repository = ? AND commit_sha = ? AND tree_sha = ? AND path = ?
              AND file_sha = ? AND symbol = ? AND symbol_kind = ?
              AND start_line = ? AND end_line = ? AND evidence_kind = ?
            """,
            identity,
        ).fetchone()
        if row is not None:
            return _source_evidence_from_row(row)
        connection.execute(
            """
            INSERT INTO source_evidence(
                id, repository, commit_sha, tree_sha, path, file_sha,
                symbol, symbol_kind, start_line, end_line, evidence_kind, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.id,
                *identity,
                source.created_at,
            ),
        )
        return source

    @staticmethod
    def _would_create_prerequisite_cycle(
        connection: sqlite3.Connection,
        *,
        goal_id: str,
        prerequisite_goal_id: str,
    ) -> bool:
        row = connection.execute(
            """
            WITH RECURSIVE ancestors(id) AS (
                SELECT prerequisite_goal_id
                FROM learning_goal_prerequisites
                WHERE goal_id = ?
                UNION
                SELECT edge.prerequisite_goal_id
                FROM learning_goal_prerequisites AS edge
                JOIN ancestors ON edge.goal_id = ancestors.id
            )
            SELECT 1 FROM ancestors WHERE id = ? LIMIT 1
            """,
            (prerequisite_goal_id, goal_id),
        ).fetchone()
        return row is not None

    @staticmethod
    def _require_topic(connection: sqlite3.Connection, topic_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM learning_topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Learning topic not found: {topic_id}")
        return row

    @staticmethod
    def _require_thread(connection: sqlite3.Connection, thread_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM chat_threads WHERE id = ?", (thread_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Chat thread not found: {thread_id}")
        return row

    @staticmethod
    def _require_goal(connection: sqlite3.Connection, goal_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM learning_goals WHERE id = ?", (goal_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Learning goal not found: {goal_id}")
        return row

    @staticmethod
    def _require_claim(connection: sqlite3.Connection, claim_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM learning_claims WHERE id = ?", (claim_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Learning claim not found: {claim_id}")
        return row

    @staticmethod
    def _require_revision(connection: sqlite3.Connection, revision_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM claim_revisions WHERE id = ?", (revision_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Claim revision not found: {revision_id}")
        return row


def _source_identity(source: SourceEvidence) -> tuple[object, ...]:
    return (
        source.repository,
        source.commit_sha,
        source.tree_sha,
        source.path,
        source.file_sha,
        source.symbol,
        source.symbol_kind,
        source.start_line,
        source.end_line,
        source.evidence_kind,
    )


def _validate_source_evidence(source: SourceEvidence) -> None:
    required = (
        source.repository,
        source.commit_sha,
        source.tree_sha,
        source.path,
        source.file_sha,
        source.evidence_kind,
    )
    if any(not value.strip() for value in required):
        raise ValueError("Source evidence identity fields are required")
    if source.start_line <= 0 or source.end_line < source.start_line:
        raise ValueError("Source evidence line range is invalid")


def _topic_from_row(row: sqlite3.Row) -> LearningTopic:
    return LearningTopic(
        id=str(row["id"]),
        title=str(row["title"]),
        scope=str(row["scope"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _goal_from_row(row: sqlite3.Row) -> LearningGoal:
    return LearningGoal(
        id=str(row["id"]),
        topic_id=str(row["topic_id"]),
        objective=str(row["objective"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _goal_context_from_row(row: sqlite3.Row) -> LearningGoalContext:
    return LearningGoalContext(
        goal_id=str(row["goal_id"]),
        thread_id=str(row["thread_id"]),
        focused_at=str(row["focused_at"]),
        focus_pinned=bool(row["focus_pinned"]),
    )


def _claim_from_row(row: sqlite3.Row) -> LearningClaim:
    return LearningClaim(
        id=str(row["id"]),
        topic_id=str(row["topic_id"]),
        scope=str(row["scope"]),
        claim_kind=str(row["claim_kind"]),
        created_at=str(row["created_at"]),
    )


def _revision_from_row(row: sqlite3.Row) -> ClaimRevision:
    return ClaimRevision(
        id=str(row["id"]),
        claim_id=str(row["claim_id"]),
        claim_text=str(row["claim_text"]),
        source_commit=str(row["source_commit"]),
        reason=str(row["reason"]),
        created_at=str(row["created_at"]),
    )


def _source_evidence_from_row(row: sqlite3.Row) -> SourceEvidence:
    return SourceEvidence(
        id=str(row["id"]),
        repository=str(row["repository"]),
        commit_sha=str(row["commit_sha"]),
        tree_sha=str(row["tree_sha"]),
        path=str(row["path"]),
        file_sha=str(row["file_sha"]),
        symbol=str(row["symbol"]),
        symbol_kind=str(row["symbol_kind"]),
        start_line=int(row["start_line"]),
        end_line=int(row["end_line"]),
        evidence_kind=str(row["evidence_kind"]),
        created_at=str(row["created_at"]),
    )


def _understanding_from_row(row: sqlite3.Row) -> UnderstandingEvidence:
    return UnderstandingEvidence(
        id=str(row["id"]),
        method=str(row["method"]),
        prompt=str(row["prompt"]),
        user_response=str(row["user_response"]),
        verified_at=str(row["verified_at"]),
    )


def _hypothesis_from_row(row: sqlite3.Row) -> LearningHypothesis:
    return LearningHypothesis(
        id=str(row["id"]),
        topic_id=str(row["topic_id"]),
        goal_id=str(row["goal_id"]),
        text=str(row["text"]),
        unresolved_reason=str(row["unresolved_reason"]),
        resolved_by_claim_id=(
            str(row["resolved_by_claim_id"])
            if row["resolved_by_claim_id"] is not None
            else None
        ),
        created_at=str(row["created_at"]),
    )


def _next_step_from_row(row: sqlite3.Row) -> NextStep:
    return NextStep(
        id=str(row["id"]),
        goal_id=str(row["goal_id"]),
        text=str(row["text"]),
        status=str(row["status"]),
        is_primary=bool(row["is_primary"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _misconception_from_row(row: sqlite3.Row) -> LearnerMisconception:
    return LearnerMisconception(
        id=str(row["id"]),
        goal_id=str(row["goal_id"]),
        description=str(row["description"]),
        status=str(row["status"]),
        occurrence_count=int(row["occurrence_count"]),
        source_eval_ref=str(row["source_eval_ref"]),
        first_seen_at=str(row["first_seen_at"]),
        last_seen_at=str(row["last_seen_at"]),
    )
