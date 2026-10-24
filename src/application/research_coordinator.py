"""CL-M3 QD-3b: the persistent coordinator that advances a research across rounds.

QD-3a made a research durable: a state row, an append-only round log, and a lease that
says which worker may write. What it deliberately did not provide is anyone to *use*
that state. This module is that someone.

The scheduling shape is borrowed from ``DeepTriggerRunner`` and nothing else is. Deep's
runner is a three-state machine (ARM, PENDING, PUBLICATION) for one specific hand-off. A
research has a different axis - which round is next - so the state machine here is the
research's own, not Deep's.

Four properties are load-bearing.

**The database is the queue.** The coordinator holds no authoritative state. Every scan
re-discovers what may be advanced from the rows themselves, so a lost wake, a crash or a
worker restart costs nothing but a scan. A coordinator that kept its own list would
have a second answer to "what is outstanding", and that second answer would survive
exactly as long as the process that holds it - which is the thing that keeps dying.

**The lease decides, not the caller.** A scan offers candidates; the repository's
compare-and-swap decides whether this worker may take one. Two workers scanning the
same row therefore produce one winner, and the loser learns it from the database rather
than from a lock held in memory. This is the whole reason the fencing token exists:
after a takeover, the old worker's late write is refused because its token is stale.

**The coordinator does not decide when a research ends.** It records what the executor
told it and refuses to add a policy of its own. Whether a research has run out of
information (R-4), whether the user cancelled it, and whether it may be upgraded a
tier are all decisions of the executor and, later, of the tier-authorisation layer.
A coordinator that also stopped researches would be a second place where "is this
over" is answered, and the two would eventually disagree.

**Bounded means bounded.** A scan takes at most ``batch_size`` researches, each
research runs at most ``rounds_per_scan`` rounds per scan, and a worker that is asked
to stop stops within a bounded join. An unbounded loop here would be a research that
never yields to the next one.

The executor is injected rather than imported, which is what lets QD-3e replace it
with a controllable fake and actually kill a process mid-round.

**The executor is synchronous.** The production round is asynchronous - the conversation
loop is an async generator - but the worker thread that calls the executor has no
event loop of its own, so the adapter drives the async round and returns when the
round is finished. Keeping the coordinator's contract synchronous means the fake
executor in QD-3e is an ordinary function and the lease/timeout behaviour can be
tested without an event loop in the picture.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
from typing import Any, Callable

from src.domain.research_state import (
    STATE_CHECKPOINTED,
    ResearchResume,
    ResearchRound,
    ResearchState,
    TIER_DEEP,
    TIER_STANDARD,
    research_request_key,
)
from src.domain.runtime_entities import utc_now
from src.repositories.research_state_repository import (
    ResearchAlreadyTerminal,
    ResearchLeaseHeld,
    ResearchNotFound,
    ResearchStateRepository,
    StaleResearchWriter,
)

SCAN_INTERVAL_SECONDS = 15.0
SCAN_BATCH = 8
ROUNDS_PER_SCAN = 1
SHUTDOWN_JOIN_SECONDS = 1.0

# A lease must outlive one round. §10.4 of the contract puts a single planning loop at
# 60-120 seconds, so 90 seconds would let a lease expire *while its round was still
# running*. The consequence would not be corruption - the fencing token refuses the
# late write - but wasted work and a replayed round, so the TTL is set above the
# longest expected round instead.
DEFAULT_LEASE_SECONDS = 300.0

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdvanceOutcome:
    """What one round of work produced.

    ``round_record`` is the finished round; the state row advances to it atomically.
    ``status`` is ``checkpointed`` while more rounds may follow and one of the terminal
    states when the research is done - ``stopped`` for a normal end, ``cancelled`` for
    the user's decision, ``failed`` for an outcome nobody chose. The executor, not the
    coordinator, decides which one applies.
    """

    round_record: ResearchRound
    status: str = STATE_CHECKPOINTED
    stop_reason: str = ""
    quota_observed: dict[str, int] | None = None
    question: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.round_record, ResearchRound):
            raise ValueError("invalid_advance_round")
        if self.status not in {STATE_CHECKPOINTED, "stopped", "cancelled", "failed"}:
            raise ValueError("invalid_advance_status")
        if not isinstance(self.stop_reason, str) or len(self.stop_reason) > 200:
            raise ValueError("invalid_advance_stop_reason")
        if not isinstance(self.question, str) or len(self.question) > 4096:
            raise ValueError("invalid_advance_question")
        if self.quota_observed is not None and not isinstance(self.quota_observed, dict):
            raise ValueError("invalid_advance_quota")


@dataclass
class CoordinatorStats:
    """What the coordinator has done. Diagnostics only; never an authority."""

    scans: int = 0
    rounds_completed: int = 0
    researches_started: int = 0
    researches_finished: int = 0
    researches_skipped: int = 0
    leases_lost: int = 0
    executor_failures: int = 0
    last_scan_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "scans": self.scans,
            "rounds_completed": self.rounds_completed,
            "researches_started": self.researches_started,
            "researches_finished": self.researches_finished,
            "researches_skipped": self.researches_skipped,
            "leases_lost": self.leases_lost,
            "executor_failures": self.executor_failures,
            "last_scan_at": self.last_scan_at,
        }


@dataclass
class ScanResult:
    """What one scan did, so a caller can assert on it without reading the database."""

    researches: int = 0
    rounds: int = 0
    finished: int = 0
    skipped: int = 0
    leases_lost: int = 0
    failures: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "researches": self.researches,
            "rounds": self.rounds,
            "finished": self.finished,
            "skipped": self.skipped,
            "leases_lost": self.leases_lost,
            "failures": self.failures,
        }


@dataclass(frozen=True)
class ResearchLease:
    """The right to write one research, held for the duration of one round.

    The token is the identity that survives a takeover: the repository compares it on
    every write, so a worker whose lease was taken over cannot write afterwards. It is
    carried here rather than re-read from the row because re-reading would let a
    worker that lost its lease believe it still holds it.

    ``round_index`` is the round this lease is about to run. It is here so the
    executor can derive the *same* admission identity a replay would derive, rather
    than inventing one - see ``research_request_key`` below.
    """

    research_id: str
    owner: str
    fencing_token: int
    round_index: int = 0

    def __post_init__(self) -> None:
        for value in (self.research_id, self.owner):
            if not isinstance(value, str) or not value.strip() or len(value) > 160:
                raise ValueError("invalid_lease_identity")
        if type(self.fencing_token) is not int or self.fencing_token < 1:
            raise ValueError("invalid_fencing_token")
        if type(self.round_index) is not int or self.round_index < 0:
            raise ValueError("invalid_lease_round_index")

    def request_key(self, stage: str) -> str:
        """The admission identity for one call in this round.

        Derived, not allocated. A worker that replays a round after a crash derives
        the same key the first attempt derived, so the ledger's own unique constraint
        rejects the duplicate instead of this layer guessing whether it was paid
        for. A coordinator that allocated a fresh key per attempt would turn every
        replay into a second charge.
        """

        return research_request_key(self.research_id, self.round_index, stage)


Executor = Callable[[ResearchResume, ResearchLease], AdvanceOutcome | None]


class ResearchCoordinator:
    """One background worker that advances persistent researches, one round at a time.

    The worker holds no authoritative state: the rows are the queue, and every scan
    re-discovers them. What it does hold is an owner name and a fencing token, which
    is not state but identity - it is what the database compares against when it
    decides whether this worker may write.
    """

    def __init__(
        self,
        repository: ResearchStateRepository,
        *,
        executor: Executor | None = None,
        owner: str = "",
        interval_seconds: float = SCAN_INTERVAL_SECONDS,
        batch_size: int = SCAN_BATCH,
        rounds_per_scan: int = ROUNDS_PER_SCAN,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        logger: logging.Logger | None = None,
    ):
        self.repository = repository
        self.executor = executor
        self.owner = owner or self._default_owner()
        self.interval_seconds = max(0.0, float(interval_seconds))
        self.batch_size = max(0, int(batch_size))
        self.rounds_per_scan = max(1, int(rounds_per_scan))
        self.lease_seconds = max(1.0, float(lease_seconds))
        self.logger = logger or _logger
        self.stats = CoordinatorStats()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _default_owner() -> str:
        """A name that is unique per worker *instance*, not per process.

        Uniqueness per process would let a restarted worker inherit its predecessor's
        lease, because the owner name would match. The fencing token catches that case
        too, but a name that is unique from the start makes the takeover obvious in a
        log instead of subtle in a row.
        """

        import uuid

        return f"research-coordinator-{uuid.uuid4().hex[:12]}"

    # --- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        """Idempotent: a second start never creates a second worker."""

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._wake.clear()
            thread = threading.Thread(
                target=self._run, name="research-coordinator", daemon=True
            )
            self._thread = thread
            thread.start()

    def stop(self) -> None:
        """Bounded shutdown: never waits out a long round."""

        self._stop.set()
        self._wake.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=SHUTDOWN_JOIN_SECONDS)

    def wake(self) -> None:
        """Signal the worker. Never runs work inline and never blocks the caller."""

        self._wake.set()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    # --- worker --------------------------------------------------------------------

    def _run(self) -> None:
        # Immediate recovery scan: a restart must not wait out the first interval.
        self._safe_scan()
        while not self._stop.is_set():
            self._wake.wait(timeout=self.interval_seconds)
            self._wake.clear()
            if self._stop.is_set():
                break
            self._safe_scan()

    def _safe_scan(self) -> None:
        try:
            self.scan_once()
        except Exception:  # pragma: no cover - defensive: the worker must survive
            self.logger.exception("research coordinator scan failed")

    # --- scan ----------------------------------------------------------------------

    def scan_once(self) -> ScanResult:
        """One scan: discover, claim, advance, checkpoint. Bounded at both ends.

        The order matters. Candidates are discovered first and each one is *claimed*
        before any work starts, so two workers that discover the same research cannot
        both run it - the second one is refused by the database, not by luck.
        """

        result = ScanResult()
        self.stats.scans += 1
        try:
            candidates = self.repository.resumable(limit=self.batch_size)
        except Exception:
            self.logger.exception("research coordinator discovery failed")
            return result

        for state in candidates:
            if self._stop.is_set():
                break
            result = self._merge(result, self._advance(state))

        self.stats.rounds_completed += result.rounds
        self.stats.researches_started += result.researches
        self.stats.researches_finished += result.finished
        self.stats.researches_skipped += result.skipped
        self.stats.leases_lost += result.leases_lost
        self.stats.executor_failures += result.failures
        self.stats.last_scan_at = utc_now()
        return result

    @staticmethod
    def _merge(left: ScanResult, right: ScanResult) -> ScanResult:
        return ScanResult(
            researches=left.researches + right.researches,
            rounds=left.rounds + right.rounds,
            finished=left.finished + right.finished,
            skipped=left.skipped + right.skipped,
            leases_lost=left.leases_lost + right.leases_lost,
            failures=left.failures + right.failures,
        )

    def _advance(self, state: ResearchState) -> ScanResult:
        """Take one research and run its next round, if this worker may.

        Every exit path leaves the database as the sole authority: either a round is
        checkpointed, or the lease is handed back, or the row is left exactly as it
        was found.
        """

        result = ScanResult()
        try:
            claimed = self.repository.claim(
                state.research_id, owner=self.owner, ttl_seconds=self.lease_seconds
            )
        except ResearchLeaseHeld:
            # Another worker owns it. That is contention, not an error: the row stays
            # exactly as it is and will be rediscovered when that lease expires.
            result.leases_lost += 1
            result.skipped += 1
            return result
        except (ResearchAlreadyTerminal, ResearchNotFound):
            result.skipped += 1
            return result

        lease = ResearchLease(
            research_id=claimed.research_id,
            owner=self.owner,
            fencing_token=claimed.fencing_token,
            round_index=claimed.round_index,
        )
        research_id = claimed.research_id
        version = claimed.state_version
        rounds = 0
        finished = 0

        try:
            resume = self.repository.resume(research_id)
        except Exception:
            self.logger.exception("research coordinator resume failed")
            self._release(lease)
            result.failures += 1
            result.skipped += 1
            return result
        if resume is None:
            self._release(lease)
            result.skipped += 1
            return result

        for _ in range(self.rounds_per_scan):
            if self._stop.is_set():
                break

            # Renew before the round. If the lease was taken over while this worker
            # was between rounds, the renewal is where it finds out - before doing
            # any more work, not after.
            try:
                self.repository.renew(
                    research_id,
                    owner=lease.owner,
                    fencing_token=lease.fencing_token,
                    ttl_seconds=self.lease_seconds,
                )
            except StaleResearchWriter:
                result.leases_lost += 1
                result.skipped += 1
                return result

            try:
                outcome = self.executor(resume, lease) if self.executor else None
            except Exception:
                # A failed callback leaves no durable mark. The lease is handed back
                # so the research is rediscovered, and the failure is not mistaken for
                # a decision about the research.
                self.logger.exception(
                    "research coordinator executor failed for %s", research_id
                )
                result.failures += 1
                self._release(lease)
                return result

            if outcome is None:
                # The executor declined to record a round. That is its decision to
                # make - it may be waiting for authorisation, for a tier upgrade or
                # for information it does not have. The coordinator records nothing
                # and stops touching this research for this scan.
                result.skipped += 1
                self._release(lease)
                return result

            try:
                updated = self.repository.checkpoint(
                    research_id,
                    outcome.round_record,
                    owner=lease.owner,
                    fencing_token=lease.fencing_token,
                    expected_state_version=version,
                    question=outcome.question or None,
                    status=outcome.status,
                    stop_reason=outcome.stop_reason or None,
                    quota_observed=outcome.quota_observed,
                )
            except StaleResearchWriter:
                # Somebody else owns this research now. Our work is discarded, and
                # the durable state stays whatever the new owner wrote.
                result.leases_lost += 1
                self._release(lease)
                return result
            except Exception:
                self.logger.exception("research coordinator checkpoint failed")
                result.failures += 1
                self._release(lease)
                return result

            rounds += 1
            if updated.terminal:
                finished = 1
                break

            # The next round continues from what was just written, so the executor
            # sees the evidence this round produced and does not repeat its queries.
            refreshed = self.repository.resume(research_id)
            if refreshed is None:
                break
            resume = refreshed
            version = updated.state_version
            # The lease follows the round. Its request identity is derived from the
            # round index, so a lease that still carried the previous round's index
            # would derive the previous round's key - and the ledger would refuse a
            # call that is actually new as a duplicate of one already paid for.
            lease = ResearchLease(
                research_id=updated.research_id,
                owner=self.owner,
                fencing_token=updated.fencing_token,
                round_index=updated.round_index,
            )

        result.rounds = rounds
        result.finished = finished
        result.researches = 1
        if finished == 0:
            # The research is still open. Hand the lease back so the next scan - of
            # this worker or of another - can continue it without waiting out the
            # TTL. A terminal checkpoint already returned the lease itself.
            self._release(lease)
        return result

    def _release(self, lease: ResearchLease) -> None:
        """Hand the lease back so the research need not wait out the TTL."""

        try:
            self.repository.release(
                lease.research_id, owner=lease.owner, fencing_token=lease.fencing_token
            )
        except Exception:  # pragma: no cover - defensive
            self.logger.exception("research coordinator release failed")


def tier_of(state: ResearchState) -> str:
    """The tier a research runs at. A coordinator never changes it."""

    if state.tier not in {TIER_STANDARD, TIER_DEEP}:
        raise ValueError("invalid_research_tier")
    return state.tier


__all__ = [
    "AdvanceOutcome",
    "CoordinatorStats",
    "DEFAULT_LEASE_SECONDS",
    "Executor",
    "ROUNDS_PER_SCAN",
    "SCAN_BATCH",
    "SCAN_INTERVAL_SECONDS",
    "SHUTDOWN_JOIN_SECONDS",
    "ResearchCoordinator",
    "ResearchLease",
    "ScanResult",
    "tier_of",
]
