"""T16/T17/M6: run production boundaries against real durable-truth snapshots."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.api.routes import session_routes
from src.application.chat_service import ChatCommand
from src.application.deep_publication import DeepPublicationService
from src.application.learning_resume import LearningResumeService
from src.application.standard_continuation import StandardContinuationService
from src.domain.learning_truth import UnderstandingClaimResult, UnderstandingEvidence
from tests.test_chat_service import _service as chat_service
from tests.test_deep_publication import ctx as deep_publication_context  # noqa: F401
from tests.test_learning_closure_truth import (
    _convergence,
    _evaluation,
    _run,
    _service as closure_service,
)
from tests.test_lookup_terminal import QUERY, deterministic_trace
from tests.test_standard_handoff import Gateway, saved_parent as saved_parent  # noqa: F401
from tests.test_deep_publication import planner


def _snapshot(database):
    with database.connect() as connection:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            if row[0].startswith(("learning_", "claim_", "understanding_"))
            or row[0] in {"source_evidence", "next_steps", "learner_misconceptions"}
        ]
        return {
            name: tuple(
                sorted(
                    (
                        tuple(row)
                        for row in connection.execute(f'SELECT * FROM "{name}"')
                    ),
                    key=repr,
                )
            )
            for name in names
        }


def _assert_isolated(database, action):
    before = _snapshot(database)
    assert before["understanding_evidence"], (
        "Use populated mastery, not just empty tables"
    )
    action()
    assert _snapshot(database) == before, "Research/UI changed durable learning truth"


def _seed_truth(repository):
    database, truth, _source, closure = closure_service(
        repository.database.path.parent, _convergence(), _evaluation("accept")
    )
    result = closure.commit(_run())
    assert result.status == "claim_validated"
    assert database.path == repository.database.path
    return truth


def _write_unauthorized_mastery(truth):
    # M6: simulate a production boundary mistakenly calling the actual writer.
    with truth.database.connect() as connection:
        revision_id = connection.execute(
            "SELECT id FROM claim_revisions LIMIT 1"
        ).fetchone()[0]
    evidence = UnderstandingEvidence(
        prompt="M6 mutation", user_response="UI/research success"
    )
    truth.create_understanding_evidence(
        evidence, (UnderstandingClaimResult(evidence.id, revision_id, "pass"),)
    )


@pytest.fixture
def isolation_case(request, tmp_path, runtime_test_context, monkeypatch):
    kind = request.param
    if kind == "lookup":
        service, repository = chat_service(tmp_path)
        service.dependencies = replace(
            service.dependencies,
            resolve_web_tools=lambda *_args, **_kwargs: deterministic_trace(),
            chat=lambda *_args, **_kwargs: pytest.fail(
                "No answer model for field lookup"
            ),
        )

        def action():
            prepared = service.start_turn(
                ChatCommand(user_input=QUERY, thread_id="thread-1")
            )
            service.generate(prepared)
            turn = repository.get_chat_turn(prepared.turn.id)
            assert turn.rag_snapshot["lookup_terminal"]["state"] == "ESCALATE_STANDARD"

        owner, method = service, "complete_turn"
    elif kind == "standard":
        repository, runs, parent, created = request.getfixturevalue("saved_parent")
        service = StandardContinuationService(
            repository,
            runs,
            Gateway(),
            clock=lambda: created + timedelta(seconds=3),
            planner_factory=lambda: planner,
        )

        def action():
            outcome = service.continue_pending(
                parent_turn_id=parent.id, thread_id=parent.thread_id
            )
            assert outcome.status == "completed" and outcome.child_run_id
            assert outcome.result["publication_authority"] is False

        owner, method = service, "continue_pending"
    elif kind == "deep4a":
        _publication, repository, runs, parent, _prepared = request.getfixturevalue(
            "deep_publication_context"
        )
        service = DeepPublicationService(repository, runs)

        def action():
            outcome = service.process(
                parent_turn_id=parent.id, thread_id=parent.thread_id
            )
            assert outcome.status == "audited"
            assert outcome.result["publication_authority"] is False
            assert outcome.result["judge_authority"] == "none"

        owner, method = service, "process"
    else:
        assert kind == "ui"
        repository = runtime_test_context.repository
        owner, method = runtime_test_context.session_service, "get_session"

        def action():
            with TestClient(app) as client:
                for url in (
                    "/sessions",
                    "/sessions/thread-1",
                    "/sessions/thread-1/learning-resume",
                ):
                    assert client.get(url).status_code == 200
                assert (
                    client.patch(
                        "/sessions/thread-1/title", json={"title": "UI rename"}
                    ).status_code
                    == 200
                )

    truth = _seed_truth(repository)
    if kind == "ui":
        monkeypatch.setattr(
            session_routes,
            "get_learning_resume_service",
            lambda: LearningResumeService(truth),
        )
    return repository.database, action, owner, method, truth


@pytest.mark.parametrize(
    "isolation_case", ["lookup", "standard", "deep4a", "ui"], indirect=True
)
def test_research_and_ordinary_ui_preserve_populated_durable_truth(isolation_case):
    database, action, _owner, _method, _truth = isolation_case
    _assert_isolated(database, action)


@pytest.mark.parametrize(
    "isolation_case", ["lookup", "standard", "deep4a", "ui"], indirect=True
)
def test_m6_writer_mutation_is_detected_at_each_real_boundary(
    isolation_case, monkeypatch
):
    database, action, owner, method, truth = isolation_case
    original = getattr(owner, method)

    def mutated(*args, **kwargs):
        result = original(*args, **kwargs)
        _write_unauthorized_mastery(truth)
        return result

    monkeypatch.setattr(owner, method, mutated)
    with pytest.raises(AssertionError, match="changed durable learning truth"):
        _assert_isolated(database, action)
    # The mutant really persisted a new passing Understanding record.
    assert len(_snapshot(database)["understanding_evidence"]) > 1


def test_explicit_authorized_closure_changes_only_the_corresponding_truth(tmp_path):
    database, truth, _source, closure = closure_service(
        tmp_path, _convergence(), _evaluation("accept")
    )
    before = _snapshot(database)
    assert before["understanding_evidence"] == ()
    result = closure.commit(_run())
    after = _snapshot(database)
    assert result.status == "claim_validated"
    assert len(after["understanding_evidence"]) == 1
    assert truth.get_focus_goal("thread-1").id == result.goal_id
    assert truth.list_understanding_for_revision(result.claim_revision_id)
    assert closure.commit(_run()) == result
    # An explicit repeated closure may refresh the goal-context timestamp;
    # immutable facts and passing Understanding records remain exactly once.
    repeated = _snapshot(database)
    assert {k: v for k, v in repeated.items() if k != "learning_goal_contexts"} == {
        k: v for k, v in after.items() if k != "learning_goal_contexts"
    }
