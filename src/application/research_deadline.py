"""Process-local finalization deadline for bounded public research only."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import time
from typing import Any, Callable, Iterator, cast


def remaining_seconds(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("research_finalization_deadline")
    return remaining


def request_options(deadline: float | None) -> dict[str, float]:
    remaining = remaining_seconds(deadline)
    return {"timeout": remaining} if remaining is not None else {}


def bounded_model_call(deadline: float | None, function: Callable[[], Any]) -> Any:
    if deadline is None:
        return function()
    remaining = remaining_seconds(deadline)
    # This worker performs inference only, with no persistence or publication.
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research-answer")
    future = executor.submit(copy_context().run, function)
    try:
        return future.result(timeout=remaining)
    finally:
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)


def bounded_stream(deadline: float | None, source: Iterator[str]) -> Iterator[str]:
    if deadline is None:
        yield from source
        return
    sentinel = object()
    # Keep one Context for the generator lifecycle, including close().
    # Copying anew for every next() would discard context changes across yields.
    worker_context = copy_context()
    executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="research-answer-stream"
    )
    try:
        while True:
            remaining = remaining_seconds(deadline)
            future = executor.submit(worker_context.run, next, source, sentinel)
            token = future.result(timeout=remaining)
            remaining_seconds(deadline)
            if token is sentinel:
                return
            yield cast(str, token)
    finally:
        # Close on the same worker after any blocked next() returns. Never close
        # an executing generator from another thread, and never wait for it here.
        close = getattr(source, "close", None)
        if callable(close):
            executor.submit(worker_context.run, close)
        executor.shutdown(wait=False, cancel_futures=False)
