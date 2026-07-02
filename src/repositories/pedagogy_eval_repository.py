"""SQLite read ownership and transaction writer for PedagogyEvalRun."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.pedagogy.evaluation import PedagogyEvalRun, SemanticEvaluation


class PedagogyEvalRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()

    @staticmethod
    def insert(
        connection: sqlite3.Connection,
        *,
        run: PedagogyEvalRun,
        thread_id: str,
        turn_id: str,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO pedagogy_eval_runs(
                id, thread_id, turn_id, learner_input, objective, protocol,
                expected_concepts, evidence, deterministic_result, semantic_result,
                confidence, final_decision, reasons, evaluator_version,
                prompt_version, schema_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                thread_id,
                turn_id,
                run.learner_input,
                run.objective,
                run.protocol,
                _dump(run.expected_concepts),
                _dump(run.evidence),
                _dump(run.deterministic_result),
                _dump(asdict(run.semantic_result)) if run.semantic_result else None,
                run.confidence,
                run.final_decision,
                _dump(run.reasons),
                run.evaluator_version,
                run.prompt_version,
                run.schema_version,
                created_at,
            ),
        )

    def get_for_turn(self, turn_id: str) -> PedagogyEvalRun | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM pedagogy_eval_runs WHERE turn_id = ?", (turn_id,)
            ).fetchone()
        return _from_row(row) if row else None

    def list_for_thread(self, thread_id: str) -> list[PedagogyEvalRun]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM pedagogy_eval_runs
                WHERE thread_id = ? ORDER BY created_at, id
                """,
                (thread_id,),
            ).fetchall()
        return [_from_row(row) for row in rows]


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _from_row(row: sqlite3.Row) -> PedagogyEvalRun:
    semantic_raw = json.loads(row["semantic_result"]) if row["semantic_result"] else None
    semantic = (
        SemanticEvaluation(
            claims=tuple(semantic_raw.get("claims", ())),
            correct_points=tuple(semantic_raw.get("correct_points", ())),
            gaps=tuple(semantic_raw.get("gaps", ())),
            misconceptions=tuple(semantic_raw.get("misconceptions", ())),
            reasoning_complete=semantic_raw.get("reasoning_complete") is True,
            transfer_ready=semantic_raw.get("transfer_ready") is True,
            confidence=float(semantic_raw.get("confidence", 0.0)),
            evidence_refs=tuple(semantic_raw.get("evidence_refs", ())),
        )
        if semantic_raw
        else None
    )
    return PedagogyEvalRun(
        id=row["id"],
        learner_input=row["learner_input"],
        objective=row["objective"],
        protocol=row["protocol"],
        expected_concepts=tuple(json.loads(row["expected_concepts"])),
        evidence=tuple(json.loads(row["evidence"])),
        deterministic_result=dict(json.loads(row["deterministic_result"])),
        semantic_result=semantic,
        confidence=float(row["confidence"]),
        final_decision=row["final_decision"],
        reasons=tuple(json.loads(row["reasons"])),
        evaluator_version=row["evaluator_version"],
        prompt_version=row["prompt_version"],
        schema_version=row["schema_version"],
    )
