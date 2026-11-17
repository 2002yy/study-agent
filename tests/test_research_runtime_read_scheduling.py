"""Pure read-admission regression checks without models or external traffic."""

from src.application import research_runtime_read_scheduling as read_scheduling
from src.web.research.runtime import RuntimeReadOutcome
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


BACKENDS = ("native_http", "wigolo_http")


def _schedule(
    candidate_id: str,
    *,
    outcomes: tuple[RuntimeReadOutcome, ...] = (),
    context: dict | None = None,
    breaker=None,
    remaining=lambda: 35.0,
):
    return read_scheduling.schedule_active_research_read(
        candidate_id=candidate_id,
        url="https://example.org/article",
        read_outcomes=outcomes,
        context=context if context is not None else {},
        breaker=breaker,
        available_backends=BACKENDS,
        research_seconds_left=remaining,
    )


def test_candidate_attempt_history_is_scoped_and_does_not_mutate_cursor() -> None:
    prior = (
        RuntimeReadOutcome(candidate_id="other", status="failed", backend="native_http"),
        RuntimeReadOutcome(candidate_id="target", status="failed", backend="native_http"),
    )
    context: dict = {}
    own = _schedule("target", outcomes=prior, context=context)
    other = _schedule("fresh", outcomes=prior, context=context)

    assert own.executable and own.backend == "wigolo_http"
    assert other.executable and other.backend == "native_http"
    assert len(prior) == 2
    entries = context[ACTIVE_RESEARCH_METRICS_KEY]["read_scheduling"]
    assert [entry["candidate_id"] for entry in entries] == ["target", "fresh"]


def test_blocked_backends_defer_without_creating_read_outcome() -> None:
    class _OpenBreaker:
        def state_for(self, *, backend: str, host: str) -> str:
            assert host == "example.org"
            assert backend in BACKENDS
            return "open"

    context: dict = {}
    outcome = _schedule("target", context=context, breaker=_OpenBreaker())

    assert not outcome.executable
    assert outcome.action == "defer"
    assert set(outcome.blocked_backends) == set(BACKENDS)
    assert context[ACTIVE_RESEARCH_METRICS_KEY]["read_scheduling"][-1][
        "action"
    ] == "defer"


def test_scheduling_metrics_reset_invalid_history_and_keep_latest_sixty() -> None:
    context = {ACTIVE_RESEARCH_METRICS_KEY: {"read_scheduling": "legacy"}}
    _schedule("first", context=context)
    for index in range(65):
        _schedule(f"candidate-{index}", context=context)

    entries = context[ACTIVE_RESEARCH_METRICS_KEY]["read_scheduling"]
    assert len(entries) == 60
    assert entries[0]["candidate_id"] == "candidate-5"
    assert entries[-1]["candidate_id"] == "candidate-64"
    legacy = {ACTIVE_RESEARCH_METRICS_KEY: "bad-metrics"}
    assert _schedule("still-schedulable", context=legacy).executable
    assert legacy[ACTIVE_RESEARCH_METRICS_KEY] == "bad-metrics"


def test_research_clock_sampled_after_candidate_attempt_history(monkeypatch) -> None:
    observed: list[str] = []
    original = read_scheduling.attempted_read_backends

    def tracked(outcomes, candidate_id):
        observed.append("attempt_history")
        return original(outcomes, candidate_id)

    monkeypatch.setattr(read_scheduling, "attempted_read_backends", tracked)

    def remaining() -> float:
        observed.append("remaining_window")
        return 27.0

    _schedule("target", remaining=remaining)
    assert observed == ["attempt_history", "remaining_window"]
