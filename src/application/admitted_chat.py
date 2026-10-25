"""CL-M3-S2-B1-2b: chat-shaped calls that go through both tracks.

`ChatService` calls `chat(messages, model_profile=..., max_tokens=...)`, which is
not the keyword surface `AdmittedCompletion` exposes. This module adapts the two
shapes without changing either: the service keeps calling `chat`, and the
wrapper turns one call into a logical reservation, a cost reservation, an
authorized send, and one observation.

**Streaming is not "one send".** A generator can be created and never advanced,
or advanced and abandoned. The authorization therefore covers the iteration,
not the call that produced the iterator: the reservation happens when the first
token is pulled, the send runs inside `pre_reserved_send`, and the observation
is written on exhaustion. A stream closed early is `unresolved` - the provider
may already have been paid for a completion nobody read.

**Empty input sends nothing.** `chat([])` returns "" without a provider call, so
it is not admitted and not reserved.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable, Iterator

from src.domain.spend_settlement import (
    COST_BASIS_ESTIMATED,
    EVIDENCE_WORKER_RECEIPT,
    SETTLEMENT_SETTLED,
    SETTLEMENT_UNRESOLVED,
    evidence_ref,
)
from src.llm_spend_guard import (
    DEFAULT_OUTPUT_TOKENS,
    cny_to_micros,
    reservation_cny,
    serialized_request_chars,
)
from src.web.semantic_admission import (
    TRANSPORT_REQUEST_OVERHEAD_CHARS,
    AdmittedCompletion,
)


def _send_identity(scope: str, task_name: str | None) -> str:
    """A round-scoped send id derived from the turn and the caller's task name.

    The admission layer identifies a send as ``operation#round#stage``; a chat
    call may pass a bare stage (or nothing), so the turn supplies the operation
    and the call is round 1 of that turn. A stage that already has the full shape
    is passed through untouched.
    """

    candidate = task_name if isinstance(task_name, str) else ""
    parts = candidate.split("#")
    if (
        len(parts) == 3
        and parts[0]
        and parts[1].startswith("r")
        and parts[1][1:].isdigit()
        and parts[2]
    ):
        return candidate
    scope_id = str(scope or "chat").replace("#", "-")
    stage = (candidate or "chat").replace("#", "-")
    return f"{scope_id}#r1#{stage}"


def _estimate_cost(
    admission, messages: list[dict[str, Any]], max_tokens: int | None, model: str
):
    """The reservation's input bound and the observation's price.

    The bound must cover what the transport will actually price. `llm_client`
    hashes the whole serialized request - model, temperature, timeout, output
    limit, response format, extra body - not just the message bodies. Measuring
    only `messages` produced a smaller reservation than the send, and the
    transport then refused its own already-authorized send. Same accounting, same
    overhead allowance as the non-streaming path.
    """

    prompt_chars = (
        serialized_request_chars(
            {"messages": messages, "model": model, "max_tokens": int(max_tokens or DEFAULT_OUTPUT_TOKENS)}
        )
        + TRANSPORT_REQUEST_OVERHEAD_CHARS
    )
    resolved_max = int(max_tokens or DEFAULT_OUTPUT_TOKENS)

    def price(tokens: int) -> int:
        return cny_to_micros(
            reservation_cny(
                prompt_chars=prompt_chars,
                max_tokens=int(tokens),
                attempts=admission.attempts,
            )
        )

    return prompt_chars, resolved_max, price


def admitted_completion_for(
    base_completion: Callable[..., str],
    admission,
    *,
    estimate_output_tokens: int = DEFAULT_OUTPUT_TOKENS,
):
    """An `AdmittedCompletion` for a caller that knows the attempt budget.

    The settled cost is estimated from the real prompt size and the output
    estimate, priced by the ledger's own function, so the observation is not a
    token-only guess.
    """

    def cost_micros_for(prompt_chars: int, output_tokens: int) -> int:
        return cny_to_micros(
            reservation_cny(
                prompt_chars=prompt_chars,
                max_tokens=output_tokens,
                attempts=admission.attempts,
            )
        )

    return AdmittedCompletion(
        base_completion,
        logical=admission.logical,
        ledger=admission.adapter,
        model=admission.model,
        price_micros=lambda tokens: cost_micros_for(0, tokens),
        estimate_output_tokens=estimate_output_tokens,
        cost_micros_for=cost_micros_for,
    )


def admitted_chat(
    base_chat: Callable[..., str],
    admission,
    *,
    scope: str,
) -> Callable[..., str]:
    """Wrap a non-streaming chat callable with both tracks."""

    def call(messages, *, task_name: str | None = None, timeout=None, **kwargs):
        if not messages:
            return base_chat(messages, **kwargs)
        _, resolved_max, price = _estimate_cost(
            admission, messages, kwargs.get("max_tokens"), admission.model
        )
        admitted = AdmittedCompletion(
            base_chat,
            logical=admission.logical,
            ledger=admission.adapter,
            model=admission.model,
            price_micros=price,
            estimate_output_tokens=resolved_max,
        )
        return admitted(
            messages=messages,
            timeout=timeout,
            task_name=_send_identity(scope, task_name),
            **kwargs,
        )

    return call


def admitted_stream_chat(
    base_stream: Callable[..., Iterator[str]],
    admission,
    *,
    scope: str,
) -> Callable[..., Iterator[str]]:
    """Wrap a streaming chat callable; the authorization covers the iteration."""

    def call(messages, *, task_name: str | None = None, timeout=None, **kwargs):
        request_id = _send_identity(scope, task_name)
        prompt_chars, resolved_max, price = _estimate_cost(
            admission, messages, kwargs.get("max_tokens"), admission.model
        )

        def stream() -> Iterator[str]:
            verdict = admission.logical.reserve(
                request_id, prompt_chars, resolved_max
            )
            if verdict != "reserved":
                raise _refused(verdict)
            if admission.adapter.reserve(
                request_id,
                model=admission.model,
                max_output_tokens=resolved_max,
                prompt_chars=prompt_chars,
            ) != "reserved":
                raise _refused("cost_ledger_refused")
            authorization = _claim(admission, request_id)
            with _authorized(authorization):
                for token in base_stream(
                    messages, task_name=request_id, timeout=timeout, **kwargs
                ):
                    yield token
            admission.adapter.settle(
                request_id,
                outcome=SETTLEMENT_SETTLED,
                cost_micros=price(resolved_max),
                cost_basis=COST_BASIS_ESTIMATED,
                evidence_ref=evidence_ref(
                    kind=EVIDENCE_WORKER_RECEIPT,
                    request_key=request_id,
                    receipt="stream:completed",
                ),
            )

        def guarded() -> Iterator[str]:
            try:
                yield from stream()
            except GeneratorExit:
                _settle_unresolved(admission, request_id)
                raise
            except BaseException:
                _settle_unresolved(admission, request_id)
                raise

        return guarded()

    return call


def admitted_async_stream_chat(
    base_stream: Callable[..., AsyncIterator[str]],
    admission,
    *,
    scope: str,
) -> Callable[..., AsyncIterator[str]]:
    """Async counterpart of :func:`admitted_stream_chat`."""

    def call(messages, *, task_name: str | None = None, timeout=None, **kwargs):
        request_id = _send_identity(scope, task_name)
        prompt_chars, resolved_max, price = _estimate_cost(
            admission, messages, kwargs.get("max_tokens"), admission.model
        )

        async def stream() -> AsyncIterator[str]:
            verdict = admission.logical.reserve(
                request_id, prompt_chars, resolved_max
            )
            if verdict != "reserved":
                raise _refused(verdict)
            if admission.adapter.reserve(
                request_id,
                model=admission.model,
                max_output_tokens=resolved_max,
                prompt_chars=prompt_chars,
            ) != "reserved":
                raise _refused("cost_ledger_refused")
            authorization = _claim(admission, request_id)
            try:
                with _authorized(authorization):
                    async for token in base_stream(
                        messages, task_name=request_id, timeout=timeout, **kwargs
                    ):
                        yield token
            except BaseException:
                _settle_unresolved(admission, request_id)
                raise
            admission.adapter.settle(
                request_id,
                outcome=SETTLEMENT_SETTLED,
                cost_micros=price(resolved_max),
                cost_basis=COST_BASIS_ESTIMATED,
                evidence_ref=evidence_ref(
                    kind=EVIDENCE_WORKER_RECEIPT,
                    request_key=request_id,
                    receipt="stream:completed",
                ),
            )

        return stream()

    return call


def _claim(admission, request_id: str):
    claim = getattr(admission.adapter, "claim_send_authorization", None)
    if not callable(claim):
        raise _refused("adapter_cannot_authorize")
    authorization = claim(request_id)
    if authorization is None:
        raise _refused("cost_ledger_refused")
    return authorization


def _authorized(authorization):
    from src.llm_spend_guard import pre_reserved_send

    return pre_reserved_send(authorization)


def _settle_unresolved(admission, request_id: str) -> None:
    try:
        admission.adapter.settle(
            request_id, outcome=SETTLEMENT_UNRESOLVED, cost_micros=None
        )
    except Exception:
        # A close path must not mask the caller's exception; the unresolved
        # settlement is retried by the turn's close when it can be.
        pass


def _refused(verdict: str) -> Exception:
    from src.web.semantic_admission import AdmissionRefused

    return AdmissionRefused(verdict)
