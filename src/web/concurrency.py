"""Bounded execution for blocking web providers and readers."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BoundedTask:
    name: str
    call: Callable[[], Any]


@dataclass(frozen=True)
class BoundedOutcome:
    name: str
    value: Any = None
    error: Exception | None = None
    timed_out: bool = False
    elapsed_ms: int = 0


def run_bounded(
    tasks: Sequence[BoundedTask],
    *,
    concurrency: int,
    total_timeout: float,
) -> list[BoundedOutcome]:
    """Run blocking calls concurrently with a request-level deadline."""
    if not tasks:
        return []
    started = time.perf_counter()
    executor = ThreadPoolExecutor(
        max_workers=max(1, min(concurrency, len(tasks))),
        thread_name_prefix="web-broker",
    )
    futures = [executor.submit(task.call) for task in tasks]
    done, pending = wait(futures, timeout=max(0.01, total_timeout))
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    outcomes: list[BoundedOutcome] = []
    for task, future in zip(tasks, futures, strict=True):
        if future in pending:
            future.cancel()
            outcomes.append(
                BoundedOutcome(
                    name=task.name,
                    timed_out=True,
                    elapsed_ms=elapsed_ms,
                )
            )
            continue
        try:
            outcomes.append(
                BoundedOutcome(
                    name=task.name,
                    value=future.result(),
                    elapsed_ms=elapsed_ms,
                )
            )
        except Exception as exc:
            outcomes.append(
                BoundedOutcome(
                    name=task.name,
                    error=exc,
                    elapsed_ms=elapsed_ms,
                )
            )
    executor.shutdown(wait=False, cancel_futures=True)
    return outcomes
