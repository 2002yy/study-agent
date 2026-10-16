"""Async Deep-1B background worker: scheduling and recovery.

Frozen contract (Async-1B-4):

* **claim** — one database transaction re-checks eligibility and takes the lease,
  persisting the authorization and lease identity (:meth:`AsyncResearchDiscovery.claim`);
* **execute** — an *independent* worker re-reads the authoritative authorization and
  establishes :func:`src.llm_spend_guard.bound_scope` in its own execution context.
  A scope is not inherited from the claiming thread: the worker creates it where the
  paid call actually happens, so thread switches, process restarts and exception
  paths all carry the right ``(auth_id, run_id)``;
* **settle** — results are written with the lease credential, and an unknown paid call
  stops the run instead of being re-issued.

Honest scope limit: a database lease cannot revoke a request that already left the
process.  When a paid call is unconfirmed, the worker *stops* the run — it never
claims that exactly-once execution was achieved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src import llm_spend_guard
from src.repositories.async_research_discovery import (
    AsyncResearchClaim,
    ClaimRefused,
)


@dataclass(frozen=True)
class WorkerOutcome:
    """What one scheduling attempt did, in the smallest honest form."""

    claimed: bool
    run_id: str = ""
    reason: str = ""
    executed: bool = False


class AsyncResearchWorker:
    """Leases authorized runs and runs them inside their own spend scope."""

    def __init__(
        self,
        *,
        discovery: Any,
        runs: Any,
        authorizations: Any,
        executor: Callable[..., Any],
        holder: str = "async-worker",
        ttl_seconds: int = 90,
    ) -> None:
        self.discovery = discovery
        self.runs = runs
        self.authorizations = authorizations
        self.executor = executor
        self.holder = holder
        self.ttl_seconds = ttl_seconds

    # -- claim ------------------------------------------------------------
    def claim_one(self, *, holder: str | None = None, limit: int = 8) -> AsyncResearchClaim | None:
        """The first candidate this worker can actually take, if any."""

        worker = holder or self.holder
        for candidate in self.discovery.discover(limit=limit):
            try:
                return self.discovery.claim(
                    candidate.run_id, holder=worker, ttl_seconds=self.ttl_seconds
                )
            except ClaimRefused as exc:
                if exc.reason == "unconfirmed_paid_call":
                    # Not retryable on its own: park the run so the worker does not
                    # spin, and leave the uncertain call visible to the user.
                    self._park(candidate.run_id, exc.reason)
                continue
        return None

    def _park(self, run_id: str, reason: str) -> None:
        try:
            self.runs.pause_run(run_id, reason=reason)
        except Exception:
            # Parking is best-effort; the claim already refused to spend.
            pass

    # -- execute ----------------------------------------------------------
    def run_once(self, *, holder: str | None = None, limit: int = 8) -> WorkerOutcome:
        claim = self.claim_one(holder=holder, limit=limit)
        if claim is None:
            return WorkerOutcome(claimed=False, reason="no_eligible_candidate")
        return self.execute_claim(claim)

    def execute_claim(self, claim: AsyncResearchClaim) -> WorkerOutcome:
        """Run one claimed run inside a scope established *here*, not inherited."""

        # The worker trusts the database, not the claiming thread's memory.
        grant = self.authorizations.get(claim.authorization_id)
        if grant is None or str(getattr(grant, "status", "")) != "active":
            self._park(claim.run_id, "authorization_gone")
            return WorkerOutcome(claimed=True, run_id=claim.run_id, reason="authorization_gone")

        with llm_spend_guard.bound_scope(grant.id, claim.run_id):
            try:
                self.executor(claim)
            except llm_spend_guard.UncertainCall as exc:
                # A paid call may already have happened; stop instead of re-paying.
                self._park(claim.run_id, "unconfirmed_paid_call")
                return WorkerOutcome(
                    claimed=True, run_id=claim.run_id, reason=f"uncertain:{exc}"
                )
            except Exception as exc:  # noqa: BLE001 - the worker must survive any run
                return WorkerOutcome(
                    claimed=True, run_id=claim.run_id, reason=f"failed:{type(exc).__name__}"
                )
        return WorkerOutcome(claimed=True, run_id=claim.run_id, executed=True)

    # -- keep-alive -------------------------------------------------------
    def heartbeat(self, claim: AsyncResearchClaim) -> Any:
        """Renew this claim's lease; only the current holder+epoch can renew."""

        return self.runs.heartbeat_lease(
            claim.run_id, holder=claim.holder, epoch=claim.epoch, ttl_seconds=self.ttl_seconds
        )
