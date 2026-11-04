"""Authenticated local skill text management; no executable installation."""

from fastapi import APIRouter, HTTPException

from src.api.models.skills import (
    SkillEnabledRequest,
    SkillImportRequest,
    SkillListResponse,
    SkillResponse,
)
from src.skills import SkillNotFoundError, SkillStore

router = APIRouter(tags=["skills"])


def _error(exc: ValueError | SkillNotFoundError) -> HTTPException:
    if isinstance(exc, SkillNotFoundError):
        return HTTPException(status_code=404, detail="Local skill not found")
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/skills", response_model=SkillListResponse)
def list_skills() -> SkillListResponse:
    try:
        return SkillListResponse(
            skills=[
                SkillResponse.model_validate(row) for row in SkillStore().list_skills()
            ]
        )
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/skills", response_model=SkillResponse)
def import_skill(request: SkillImportRequest) -> SkillResponse:
    try:
        return SkillResponse(**SkillStore().import_skill(request.content))
    except ValueError as exc:
        raise _error(exc) from exc


@router.patch("/skills/{skill_id}", response_model=SkillResponse)
def set_skill_enabled(skill_id: str, request: SkillEnabledRequest) -> SkillResponse:
    try:
        return SkillResponse(**SkillStore().set_enabled(skill_id, request.enabled))
    except (ValueError, SkillNotFoundError) as exc:
        raise _error(exc) from exc


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str) -> dict[str, bool]:
    try:
        SkillStore().delete(skill_id)
    except (ValueError, SkillNotFoundError) as exc:
        raise _error(exc) from exc
    return {"deleted": True}
