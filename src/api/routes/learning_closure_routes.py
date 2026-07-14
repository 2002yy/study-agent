"""Thin adapters for durable LearningClosureRun workflows."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.models.learning_closure import (
    LearningClosureRunListResponse,
    LearningClosureRunResponse,
)
from src.application.learning_closure_service import (
    LearningClosureNotEligible,
    LearningClosureService,
)
from src.application.runtime_repository import get_learning_closure_service

router = APIRouter(tags=["learning-closure"])
LearningClosureServiceDependency = Annotated[
    LearningClosureService,
    Depends(get_learning_closure_service),
]


def _response(
    service: LearningClosureService,
    run,
) -> LearningClosureRunResponse:
    return LearningClosureRunResponse(**service.response_payload(run))


def _not_found_or_conflict(exc: ValueError) -> HTTPException:
    detail = str(exc)
    status = 404 if "not found" in detail.lower() else 409
    return HTTPException(status_code=status, detail=detail)


@router.post(
    "/sessions/{session_id}/learning-closure-runs",
    response_model=LearningClosureRunResponse,
)
def create_learning_closure_run(
    session_id: str,
    service: LearningClosureServiceDependency,
) -> LearningClosureRunResponse:
    try:
        return _response(service, service.create_and_execute(session_id))
    except LearningClosureNotEligible as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.get(
    "/learning-closure-runs",
    response_model=LearningClosureRunListResponse,
)
def list_learning_closure_runs(
    service: LearningClosureServiceDependency,
    limit: int = 20,
) -> LearningClosureRunListResponse:
    return LearningClosureRunListResponse(
        runs=[_response(service, run) for run in service.list(limit=limit)]
    )


@router.get(
    "/learning-closure-runs/{run_id}",
    response_model=LearningClosureRunResponse,
)
def get_learning_closure_run(
    run_id: str,
    service: LearningClosureServiceDependency,
) -> LearningClosureRunResponse:
    try:
        return _response(service, service.get(run_id))
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.post(
    "/learning-closure-runs/{run_id}/retry",
    response_model=LearningClosureRunResponse,
)
def retry_learning_closure_run(
    run_id: str,
    service: LearningClosureServiceDependency,
) -> LearningClosureRunResponse:
    try:
        return _response(service, service.retry(run_id))
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.post(
    "/learning-closure-runs/{run_id}/cancel",
    response_model=LearningClosureRunResponse,
)
def cancel_learning_closure_run(
    run_id: str,
    service: LearningClosureServiceDependency,
) -> LearningClosureRunResponse:
    try:
        return _response(service, service.cancel(run_id))
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.post(
    "/learning-closure-runs/{run_id}/commit",
    response_model=LearningClosureRunResponse,
)
def commit_learning_closure_run(
    run_id: str,
    service: LearningClosureServiceDependency,
) -> LearningClosureRunResponse:
    try:
        return _response(service, service.commit(run_id))
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc
