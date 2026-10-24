"""CL-M3 QD-3e: the production wiring, and what it deliberately does not do.

QD-3e connects QD-3a (durable state), QD-3b (the coordinator), QD-3c (the
feed) and QD-3d (the termination and authorisation semantics) into a running
application. This file tests the wiring, and - more importantly - tests the
**refusals**, because the wiring's job is mostly to say no.

**Why the worker is off by default.** The coordinator advances a research by
calling an executor, and a real executor calls a model, which costs money.
So the production path does not build an executor: it takes one from the
caller. A coordinator with no executor scans, discovers nothing it may
advance, and accomplishes nothing - which is safe but useless, and a worker
that looks alive while doing nothing is worse than a worker that is not
running. The production path therefore refuses to start one.

**What these tests refuse to claim.** None of them runs a model. There is
no paid call anywhere in QD-3e, and the tests that would need one assert
the refusal instead: that the worker does not start without an executor,
and that the application still comes up when the wiring fails.
"""

from __future__ import annotations

import pytest

from src.application.research_production import (
    RESEARCH_COORDINATOR_ENABLED_ENV,
    RESEARCH_EXECUTOR_FACTORY_ENV,
    build_research_coordinator,
    load_executor_factory,
    research_coordinator_enabled,
    start_research_coordinator,
    stop_research_coordinator,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_state_repository import ResearchStateRepository
from tests.research_test_executor import ScriptedExecutor, ScriptedStep


@pytest.fixture
def repository(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.sqlite")
    database.initialize()
    return ResearchStateRepository(database)


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv(RESEARCH_COORDINATOR_ENABLED_ENV, raising=False)
    monkeypatch.delenv(RESEARCH_EXECUTOR_FACTORY_ENV, raising=False)
    return monkeypatch


# --- the worker is off unless it is turned on ----------------------------------


def test_the_research_worker_is_off_by_default(clean_env):
    """A worker that costs money does not start because a module was imported."""

    assert research_coordinator_enabled() is False


def test_the_worker_starts_only_when_it_is_turned_on(clean_env):
    """The switch is a switch, and it is read at the moment of the decision."""

    clean_env.setenv(RESEARCH_COORDINATOR_ENABLED_ENV, "1")
    assert research_coordinator_enabled() is True

    clean_env.setenv(RESEARCH_COORDINATOR_ENABLED_ENV, "off")
    assert research_coordinator_enabled() is False

    clean_env.setenv(RESEARCH_COORDINATOR_ENABLED_ENV, "TRUE")
    assert research_coordinator_enabled() is True


# --- no executor, no worker ------------------------------------------------------


def test_an_enabled_worker_without_an_executor_does_not_start(clean_env, repository):
    """Turning the switch on is not enough to spend money.

    The switch says "this deployment has a research worker". It does not
    say what the worker may do, and that is a separate question with a
    separate answer. A worker with no executor would scan forever and
    accomplish nothing, so it is not started.
    """

    clean_env.setenv(RESEARCH_COORDINATOR_ENABLED_ENV, "1")

    coordinator = start_research_coordinator(repository)

    assert coordinator is None


def test_an_enabled_worker_with_a_broken_executor_factory_does_not_start(
    clean_env, repository
):
    """A factory that cannot be imported is a startup failure, not a silent no.

    The application must still come up - a research that was not advanced is
    still durable - but the failure has to be visible, or nobody will know
    that the research feature is silently off.
    """

    clean_env.setenv(RESEARCH_COORDINATOR_ENABLED_ENV, "1")
    clean_env.setenv(RESEARCH_EXECUTOR_FACTORY_ENV, "no.such.module:factory")

    coordinator = start_research_coordinator(repository)

    assert coordinator is None


def test_a_malformed_executor_factory_is_refused(clean_env):
    """The factory is named ``module:attribute``; anything else is not a name."""

    clean_env.setenv(RESEARCH_EXECUTOR_FACTORY_ENV, "not-a-spec")

    assert load_executor_factory() is None


def test_no_executor_factory_means_no_executor(clean_env):
    """Nothing configured means nothing to import."""

    assert load_executor_factory() is None


def test_an_executor_factory_is_imported_by_path(clean_env):
    """A factory that exists is found, and called to make the executor."""

    clean_env.setenv(
        RESEARCH_EXECUTOR_FACTORY_ENV, "tests.research_test_executor:ScriptedExecutor"
    )

    factory = load_executor_factory()

    assert factory is not None
    assert callable(factory)


# --- the worker runs when it has both ------------------------------------------


def test_an_enabled_worker_with_an_executor_starts(clean_env, repository):
    """The whole switch: on, with an executor, the worker runs."""

    clean_env.setenv(RESEARCH_COORDINATOR_ENABLED_ENV, "1")
    executor = ScriptedExecutor([ScriptedStep(action="checkpoint")])

    coordinator = start_research_coordinator(repository, executor=executor)

    assert coordinator is not None
    assert coordinator.running is True
    stop_research_coordinator(coordinator)
    assert coordinator.running is False


def test_the_worker_can_be_started_with_a_configured_factory(clean_env, repository):
    """The configured factory is how a deployment supplies its executor.

    The factory is imported *at start time*, not at import time, so an
    application that never starts a research worker never imports the code
    that can call a model.
    """

    clean_env.setenv(RESEARCH_COORDINATOR_ENABLED_ENV, "1")
    clean_env.setenv(
        RESEARCH_EXECUTOR_FACTORY_ENV, "tests.research_test_executor:ScriptedExecutor"
    )

    coordinator = start_research_coordinator(repository)

    assert coordinator is not None
    assert coordinator.running is True
    stop_research_coordinator(coordinator)


def test_stopping_a_worker_that_never_started_is_harmless(clean_env):
    """Shutdown has to work when startup did not."""

    stop_research_coordinator(None)


# --- the coordinator the factory builds -----------------------------------------


def test_the_built_coordinator_keeps_the_executor_it_was_given(repository):
    """The factory does not substitute an executor of its own.

    This is the whole point of the module: the executor is the thing that
    decides whether the research may spend, so the factory passes it
    through unchanged rather than wrapping it in something of its own.
    """

    executor = ScriptedExecutor([ScriptedStep(action="checkpoint")])

    coordinator = build_research_coordinator(repository, executor=executor)

    assert coordinator.executor is executor
    assert coordinator.repository is repository


def test_a_coordinator_without_an_executor_starts_but_does_nothing(repository):
    """The two failure modes are different, and both are visible.

    A coordinator with no executor is a valid object - it scans, finds
    nothing it may advance, and records nothing. It is not what production
    uses, but it is not broken, and a test that could not build one would
    not be able to check the guard that refuses to start it.
    """

    coordinator = build_research_coordinator(repository)

    assert coordinator.executor is None
    result = coordinator.scan_once()
    assert result.rounds == 0
