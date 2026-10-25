"""CL-M3-S2-B1: the paid identity must survive the research thread hop.

`ResearchSemanticSession.request` sends the completion through
``ThreadPoolExecutor.submit``. A plain pool does not inherit ``ContextVar``
values, so the spend identity bound by the caller is invisible in the worker.
That matters twice: the transport refuses a call it cannot attribute (fail
closed, but the research round breaks), and once the admission layer is wired,
a send could be reserved under one identity and observed under none.

The fix is to submit ``contextvars.copy_context().run``. The test binds an
identity in the main thread, reads it inside the completion (which runs in the
worker), and asserts it matches. Removing the copy makes the worker see the
default, which is exactly the failure this test exists for.
"""

from __future__ import annotations

import time

from src.llm_spend_guard import current_identity, spend_identity
from src.web.semantic_recovery import ResearchSemanticSession

PAYLOAD = '{"intent": "ANSWER"}'


def test_the_research_thread_sees_the_callers_spend_identity():
    seen = []

    def completion(*, messages, timeout, task_name, **_kwargs):
        identity = current_identity()
        seen.append((identity.run_id, identity.operation_id, identity.experiment))
        return PAYLOAD

    session = ResearchSemanticSession(
        completion,
        deadline=time.monotonic() + 5.0,
        should_cancel=lambda: False,
    )

    with spend_identity(
        run_id="run-1",
        operation_id="op-1",
        invocation="1",
        experiment="exp-1",
    ):
        assert session.request("research_turn_interpretation", "sys", {"x": 1}) == {
            "intent": "ANSWER"
        }

    assert seen == [("run-1", "op-1", "exp-1")]


def test_the_research_thread_uses_the_round_scoped_task_name():
    """The admission layer requires ``operation#round#stage``, not a bare stage.

    Copying the context makes the identity visible; it does not make the name a
    send identity. The host supplies the formatter, and the worker must receive
    the formatted name.
    """

    seen = []

    def completion(*, messages, timeout, task_name, **_kwargs):
        seen.append(task_name)
        return PAYLOAD

    session = ResearchSemanticSession(
        completion,
        deadline=time.monotonic() + 5.0,
        should_cancel=lambda: False,
        task_identity=lambda stage: f"op-1#r1#{stage}",
    )

    assert session.request("research_turn_interpretation", "sys", {"x": 1}) == {
        "intent": "ANSWER"
    }
    assert seen == ["op-1#r1#research_turn_interpretation"]
