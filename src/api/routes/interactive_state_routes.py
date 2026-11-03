"""Save and read one learner's snapshot of a generated document's state.

The generated code publishes state through the sandbox bridge; only this route
writes it. Restoring is a separate, explicit action, so a stale snapshot can
never silently replace what the learner is looking at.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.models.interactive_state import (
    InteractiveStateResponse,
    InteractiveStateSaveRequest,
)
from src.application.runtime_repository import get_interactive_state_repository
from src.repositories.interactive_state_repository import (
    MAX_STATE_CHARS,
    InteractiveStateRepository,
    state_size,
)

router = APIRouter(tags=["interactive-state"])
InteractiveStateRepositoryDependency = Annotated[
    InteractiveStateRepository, Depends(get_interactive_state_repository)
]


@router.put(
    "/sessions/{session_id}/interactive-state",
    response_model=InteractiveStateResponse,
)
def save_interactive_state(
    session_id: str,
    request: InteractiveStateSaveRequest,
    repository: InteractiveStateRepositoryDependency,
) -> InteractiveStateResponse:
    if not repository.thread_exists(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    if state_size(request.state) > MAX_STATE_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"state must be at most {MAX_STATE_CHARS} characters",
        )
    snapshot = repository.upsert(
        session_id, request.component_id, request.revision, request.state
    )
    return InteractiveStateResponse(
        component_id=snapshot.component_id,
        revision=snapshot.revision,
        state=snapshot.state,
        updated_at=snapshot.updated_at,
    )


@router.get(
    "/sessions/{session_id}/interactive-state/{component_id}",
    response_model=InteractiveStateResponse,
)
def read_interactive_state(
    session_id: str,
    component_id: str,
    revision: int,
    repository: InteractiveStateRepositoryDependency,
) -> InteractiveStateResponse:
    if revision < 1 or revision > 999:
        raise HTTPException(status_code=422, detail="revision must be between 1 and 999")
    snapshot = repository.get(session_id, component_id, revision)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no saved state for this component")
    return InteractiveStateResponse(
        component_id=snapshot.component_id,
        revision=snapshot.revision,
        state=snapshot.state,
        updated_at=snapshot.updated_at,
    )
