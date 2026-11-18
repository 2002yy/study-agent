"""Cancellation lease for one active research operation.

The operation identifier is frozen when execution begins. This guard checks
the durable cancellation signal; it does not own checkpoints or budget state.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.repositories.web_lookup_repository import WebLookupRepository


class ActiveResearchCancelled(RuntimeError):
    """The active operation was cancelled at an existing safe boundary."""


@dataclass(frozen=True, slots=True)
class ActiveResearchOperationGuard:
    repository: WebLookupRepository
    run_id: str
    operation_id: str

    def ensure_active(self) -> None:
        if self.repository.cancel_requested(
            self.run_id, operation_id=self.operation_id
        ):
            raise ActiveResearchCancelled("active research cancelled")
