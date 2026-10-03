"""Read-only fences executed inside the learning-truth write transaction."""

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from src.domain.learning_closure import canonical_closure_source_hash
from src.domain.review_turn import read_review_snapshot, review_time
from src.repositories.pedagogy_eval_repository import _from_row as evaluation_from_row


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("Review commit rejected: " + reason)


def json_value(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def guard_review_attempt(connection, *, run, binding, evaluation, replay: bool) -> None:
    stored = connection.execute(
        "SELECT * FROM learning_closure_runs WHERE id = ?", (run.id,)
    ).fetchone()
    require(stored is not None, "closure owner missing")
    require(
        stored["thread_id"] == binding.thread_id == run.thread_id,
        "closure thread mismatch",
    )
    require(stored["source_hash"] == run.source_hash, "closure digest mismatch")
    require(
        stored["source_thread_version"] == run.source_thread_version,
        "closure version mismatch",
    )
    snapshot = json.loads(stored["committed_snapshot"])
    require(snapshot == json_value(run.committed_snapshot), "closure snapshot mismatch")
    require(
        canonical_closure_source_hash(
            {key: value for key, value in snapshot.items() if key != "structured_input"}
        )
        == run.source_hash,
        "source digest mismatch",
    )
    attempt = snapshot["structured_input"].get("review_attempt")
    require(
        attempt
        == json_value(
            {
                "binding": binding.to_dict(),
                "answer_turn_id": run.last_completed_turn_id,
                "evaluation_id": evaluation.id,
            }
        ),
        "frozen attempt mismatch",
    )
    require(
        stored["last_completed_turn_id"] == run.last_completed_turn_id,
        "closure answer mismatch",
    )
    require(
        stored["closure_eligibility"] == run.closure_eligibility == "learning_summary",
        "closure eligibility mismatch",
    )
    prompt = connection.execute(
        "SELECT * FROM chat_turns WHERE id = ?", (binding.prompt_turn_id,)
    ).fetchone()
    answer = connection.execute(
        "SELECT * FROM chat_turns WHERE id = ?", (run.last_completed_turn_id,)
    ).fetchone()
    require(prompt is not None and answer is not None, "turn missing")
    for row, phase in ((prompt, "prompt"), (answer, "answer")):
        require(
            row["thread_id"] == binding.thread_id and row["status"] == "completed",
            "turn ownership/status mismatch",
        )
        require(row["cancel_requested_at"] is None, "cancelled turn")
        require(
            read_review_snapshot(
                json.loads(row["route_snapshot"]).get("review"), phase=phase
            )
            == binding,
            "persisted binding mismatch",
        )
    require(prompt["assistant_message"] == binding.question, "prompt text mismatch")
    eval_row = connection.execute(
        "SELECT * FROM pedagogy_eval_runs WHERE turn_id = ?", (answer["id"],)
    ).fetchone()
    require(
        eval_row is not None and eval_row["thread_id"] == binding.thread_id,
        "evaluation owner mismatch",
    )
    require(
        asdict(evaluation_from_row(eval_row)) == asdict(evaluation),
        "evaluation payload mismatch",
    )
    require(
        answer["user_message"] == evaluation.learner_input,
        "evaluation response mismatch",
    )
    require(
        evaluation.objective == binding.objective
        and evaluation.expected_concepts == (binding.claim_text,),
        "evaluation target mismatch",
    )
    require(evaluation.evidence == binding.evidence_ids, "evaluation evidence mismatch")
    frozen_eval = snapshot["structured_input"].get("final_pedagogy_evaluation")
    require(
        frozen_eval == json_value({**asdict(evaluation), "turn_id": answer["id"]}),
        "frozen evaluation mismatch",
    )
    if replay:
        return
    require(
        stored["status"] == "committing"
        and stored["active_operation_id"] == run.active_operation_id
        and run.active_operation_id is not None,
        "closure operation lost",
    )
    require(stored["cancel_requested_at"] is None, "closure cancelled")
    thread = connection.execute(
        "SELECT * FROM chat_threads WHERE id = ?", (binding.thread_id,)
    ).fetchone()
    require(
        thread is not None
        and thread["status"] == "active"
        and thread["active_operation_id"] is None,
        "thread not idle/active",
    )
    require(thread["version"] == run.source_thread_version, "source changed")
    latest = connection.execute(
        "SELECT id FROM chat_turns WHERE thread_id = ? AND status = 'completed' ORDER BY created_at DESC, id DESC LIMIT 1",
        (binding.thread_id,),
    ).fetchone()
    require(
        latest is not None and latest["id"] == answer["id"], "answer no longer latest"
    )
    goal = connection.execute(
        """
        SELECT goal.* FROM learning_goals goal JOIN learning_goal_contexts context ON context.goal_id = goal.id
        WHERE context.thread_id = ? AND goal.status IN ('active', 'blocked')
        ORDER BY context.focus_pinned DESC, context.focused_at DESC, goal.updated_at DESC, goal.id LIMIT 1
    """,
        (binding.thread_id,),
    ).fetchone()
    require(
        goal is not None
        and goal["id"] == binding.goal_id
        and goal["objective"] == binding.objective,
        "goal changed",
    )
    revision = connection.execute(
        """
        SELECT rev.* FROM learning_goal_claim_revisions link JOIN claim_revisions rev ON rev.id = link.claim_revision_id
        WHERE link.goal_id = ? AND rev.claim_id = (SELECT claim_id FROM claim_revisions WHERE id = ?)
        ORDER BY link.created_at DESC, rev.created_at DESC, rev.id DESC LIMIT 1
    """,
        (binding.goal_id, binding.claim_revision_id),
    ).fetchone()
    require(
        revision is not None
        and revision["id"] == binding.claim_revision_id
        and revision["claim_text"] == binding.claim_text,
        "revision changed",
    )
    refs = connection.execute(
        "SELECT source_evidence_id FROM claim_revision_evidence WHERE claim_revision_id = ? ORDER BY position, source_evidence_id",
        (binding.claim_revision_id,),
    ).fetchall()
    require(
        tuple(row[0] for row in refs) == binding.evidence_ids, "source binding changed"
    )
    passes = connection.execute(
        """
        SELECT ev.verified_at FROM understanding_evidence ev JOIN understanding_evidence_claims link ON link.understanding_evidence_id = ev.id
        WHERE link.claim_revision_id = ? AND link.result = 'pass'
    """,
        (binding.claim_revision_id,),
    ).fetchall()
    require(bool(passes), "prior validation missing")
    last_pass = max(review_time(row[0]) for row in passes)
    require(last_pass == review_time(binding.last_validated_at), "last pass changed")
    require(
        datetime.now(timezone.utc) >= last_pass + timedelta(days=7),
        "review no longer due",
    )
