"""The run cancellation lease has no mutable cursor or checkpoint ownership."""

from typing import cast

import pytest

from src.application.active_research_runtime import ActiveResearchCancelled
from src.application.research_runtime_operation_guard import (
    ActiveResearchOperationGuard,
)
from src.repositories.web_lookup_repository import WebLookupRepository


class _CancellationRepository:
    def __init__(self, cancelled: bool) -> None:
        self.cancelled = cancelled
        self.calls: list[tuple[str, str]] = []

    def cancel_requested(self, run_id: str, *, operation_id: str) -> bool:
        self.calls.append((run_id, operation_id))
        return self.cancelled


def test_operation_guard_checks_only_its_frozen_operation_lease() -> None:
    repository = _CancellationRepository(cancelled=False)
    guard = ActiveResearchOperationGuard(
        repository=cast(WebLookupRepository, repository),
        run_id="research-1",
        operation_id="operation-2",
    )

    guard.ensure_active()
    repository.cancelled = True
    with pytest.raises(ActiveResearchCancelled, match="active research cancelled"):
        guard.ensure_active()

    assert repository.calls == [
        ("research-1", "operation-2"),
        ("research-1", "operation-2"),
    ]
