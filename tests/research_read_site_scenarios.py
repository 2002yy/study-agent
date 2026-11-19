"""Shared offline read-site execution scenario for selector and visual tests.

Use the real active runtime test doubles without loading its test file under
separate synthetic module names for every consumer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests import test_active_research_runtime as ART


def run_read_site_scenario(
    *,
    tmp_path: Path,
    sqlite_name: str,
    run_id: str,
    context: dict[str, Any],
) -> Any:
    """Execute the same fake-backed real reader chain with isolated SQLite."""

    repository = ART._TrackingRepository(ART.RuntimeDatabase(tmp_path / sqlite_name))
    run = repository.create(
        ART.WebLookupRun(
            id=run_id,
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )
    service = ART._service(
        repository,
        ART._StructuredClient(),
        read_gateway=ART._ShortNativeReadGateway(text="z" * 1200),
        escalation_backend=ART._CutoverEscalationBackend("y" * 1200),
    )
    return service.execute(run.id, raise_on_error=True)
