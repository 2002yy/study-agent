"""CL-M3 QD-3e: the production wiring for the persistent research.

QD-3a made a research durable, QD-3b gave something to advance it, QD-3c let
a client watch it, and QD-3d gave it a way to stop and a way to spend more.
None of the four is reachable in production until this module exists, because
none of them has a factory.

**What this module is.** A factory, a lifecycle hook, and the three
wiring decisions that are not obvious. It is deliberately small: the
behaviour lives in the layers below, and this file only decides *who talks
to whom*.

**The executor is the load-bearing part, and it is not here.** The
coordinator advances a research by calling an executor, and a real executor
calls a model - which costs money. This module therefore *does not build
one*. It takes one from the caller, and the caller is the one that decides
whether the research may spend. That is the whole point of the R-6
authorisation table: the decision to spend is not the code's to make.

So the wiring is:

- ``get_research_coordinator()`` builds the coordinator **with whatever
  executor it is handed**, and
- ``start_research_coordinator()`` starts it **only if** an executor was
  supplied.

A coordinator with no executor scans, discovers nothing it may advance, and
records nothing. That is safe but useless, so the production path refuses to
start one. The alternative - starting a worker that silently does nothing -
is worse, because it looks alive.

**Why the start is best-effort.** The application's own chat must never be
held hostage by a research worker. If the coordinator cannot start, the
application still comes up, and the research that was already durable stays
durable: it is still in the database, and the next start picks it up. That
is the same property the Deep trigger has, and it is the property that
makes "the process died" survivable rather than fatal.

**Why shutdown is bounded.** A round may be waiting on a model. Shutdown
never waits out a model call; it stops the worker and returns. The round
that was in flight is not lost - the lease expires, another worker takes
over, and the fencing token refuses the dead worker's late write.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

from src.application.research_coordinator import Executor, ResearchCoordinator
from src.repositories.research_state_repository import ResearchStateRepository

_logger = logging.getLogger(__name__)

# The environment variable that says "there is an executor, start the worker".
# It is a flag rather than a value because the executor cannot be expressed
# as configuration: it is code, and the code that builds it also decides
# whether the research is allowed to spend.
RESEARCH_COORDINATOR_ENABLED_ENV = "STUDY_AGENT_RESEARCH_COORDINATOR"

# The environment variable that names the executor factory. The factory is
# imported by path, so the wiring stays out of the import graph until it is
# actually used - importing a module that can call a model should be a
# decision, not a side effect of starting the application.
RESEARCH_EXECUTOR_FACTORY_ENV = "STUDY_AGENT_RESEARCH_EXECUTOR_FACTORY"


def research_coordinator_enabled() -> bool:
    """Whether the production research worker is allowed to run.

    Off by default. A coordinator that runs without an executor is a worker
    that scans forever and accomplishes nothing, and one that runs with a
    misconfigured executor spends money. Both are worse than not running.
    """

    return os.getenv(RESEARCH_COORDINATOR_ENABLED_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def load_executor_factory() -> Callable[[], Executor] | None:
    """Import the configured executor factory, if there is one.

    The factory is looked up as ``module:attribute`` so that the process
    which starts the application does not import the executor module - and
    therefore does not import the model client - until the research worker
    is actually being started.

    A factory that cannot be imported is a **startup failure**, not a
    silent "no executor". The caller logs it and continues without the
    worker, which is the same outcome as any other best-effort start.
    """

    spec = os.getenv(RESEARCH_EXECUTOR_FACTORY_ENV, "").strip()
    if not spec:
        return None
    module_name, _, attribute = spec.partition(":")
    if not module_name or not attribute:
        _logger.error(
            "research executor factory %r is not in module:attribute form", spec
        )
        return None
    try:
        module = __import__(module_name, fromlist=[attribute])
        factory = getattr(module, attribute)
    except Exception:
        _logger.exception("research executor factory %r could not be imported", spec)
        return None
    if not callable(factory):
        _logger.error("research executor factory %r is not callable", spec)
        return None
    return factory


def build_research_coordinator(
    repository: ResearchStateRepository,
    *,
    executor: Executor | None = None,
    owner: str = "",
    interval_seconds: float | None = None,
    batch_size: int | None = None,
) -> ResearchCoordinator:
    """Build the coordinator, with the executor the caller is willing to pay for.

    Every knob except the executor has a default that matches the
    coordinator's own. The executor does not: it is the one thing this
    module must not invent.
    """

    kwargs: dict = {}
    if owner:
        kwargs["owner"] = owner
    if interval_seconds is not None:
        kwargs["interval_seconds"] = interval_seconds
    if batch_size is not None:
        kwargs["batch_size"] = batch_size
    return ResearchCoordinator(repository, executor=executor, **kwargs)


def start_research_coordinator(
    repository: ResearchStateRepository | None = None,
    *,
    executor: Executor | None = None,
) -> ResearchCoordinator | None:
    """Start the production research worker, if it is allowed and able to.

    Returns the running coordinator, or ``None`` when it was not started.
    The caller does not have to know which happened: a research that was not
    advanced is still durable, and the next start will pick it up.
    """

    if not research_coordinator_enabled():
        _logger.info("research coordinator is disabled; not starting")
        return None

    if executor is None:
        factory = load_executor_factory()
        if factory is None:
            _logger.warning(
                "research coordinator is enabled but no executor factory is configured"
            )
            return None
        try:
            executor = factory()
        except Exception:
            _logger.exception("research executor factory failed")
            return None

    if executor is None:
        _logger.warning("research coordinator is enabled but there is no executor")
        return None

    if repository is None:
        from src.application.runtime_repository import get_research_state_repository

        repository = get_research_state_repository()

    coordinator = build_research_coordinator(repository, executor=executor)
    coordinator.start()
    if not coordinator.running:
        _logger.warning("research coordinator did not start")
        return None
    _logger.info("research coordinator started (owner=%s)", coordinator.owner)
    return coordinator


def stop_research_coordinator(coordinator: ResearchCoordinator | None) -> None:
    """Stop the worker, bounded. Never waits out a model call."""

    if coordinator is None:
        return
    try:
        coordinator.stop()
    except Exception:
        _logger.exception("research coordinator shutdown failed")


__all__ = [
    "RESEARCH_COORDINATOR_ENABLED_ENV",
    "RESEARCH_EXECUTOR_FACTORY_ENV",
    "build_research_coordinator",
    "load_executor_factory",
    "research_coordinator_enabled",
    "start_research_coordinator",
    "stop_research_coordinator",
]
