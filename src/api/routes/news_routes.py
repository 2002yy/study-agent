"""Thin HTTP adapters for server-owned NewsRun workflows."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.models.news import (
    NewsDigestRequest,
    NewsDigestResponse,
    NewsDiscussRequest,
    NewsDiscussResponse,
    NewsEnrichRequest,
    NewsEnrichResponse,
    NewsLookupRequest,
    NewsLookupResponse,
    NewsRunCreateRequest,
    NewsRunDigestRequest,
    NewsRunDiscussRequest,
    NewsRunEnrichRequest,
    NewsRunListResponse,
    NewsRunResponse,
    NewsSearchRequest,
    NewsSearchResponse,
    NewsStageSearchRequest,
    NewsStageSearchResponse,
)
from src.application.helpers import request_performance_mode, validate_choice
from src.application.news_service import NewsService
from src.application.runtime_repository import get_news_service
from src.constants import ATMOS_OPTIONS, MODEL_OPTIONS

router = APIRouter(tags=["news"])
NewsServiceDependency = Annotated[NewsService, Depends(get_news_service)]


def _response(run) -> NewsRunResponse:
    return NewsRunResponse(**asdict(run))


@router.post("/news/runs", response_model=NewsRunResponse)
def create_news_run_endpoint(
    request: NewsRunCreateRequest,
    service: NewsServiceDependency,
) -> NewsRunResponse:
    try:
        return _response(
            service.create_and_search(request.query, max_items=request.max_items)
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"News search failed: {exc}") from exc


@router.get("/news/runs", response_model=NewsRunListResponse)
def list_news_runs_endpoint(
    service: NewsServiceDependency, limit: int = 20
) -> NewsRunListResponse:
    return NewsRunListResponse(runs=[_response(run) for run in service.list(limit=limit)])


@router.get("/news/runs/{run_id}", response_model=NewsRunResponse)
def get_news_run_endpoint(run_id: str, service: NewsServiceDependency) -> NewsRunResponse:
    try:
        return _response(service.get(run_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/news/runs/{run_id}/enrich", response_model=NewsRunResponse)
def enrich_news_run_endpoint(
    run_id: str,
    request: NewsRunEnrichRequest,
    service: NewsServiceDependency,
) -> NewsRunResponse:
    try:
        return _response(
            service.enrich(
                run_id,
                max_articles=request.max_articles,
                max_chars_per_article=request.max_chars_per_article,
                safe_mode=request.safe_mode,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"News enrich failed: {exc}") from exc


@router.post("/news/runs/{run_id}/digest", response_model=NewsRunResponse)
def digest_news_run_endpoint(
    run_id: str,
    request: NewsRunDigestRequest,
    service: NewsServiceDependency,
) -> NewsRunResponse:
    validate_choice(request.selected_model, MODEL_OPTIONS, "selected_model")
    try:
        return _response(
            service.digest(
                run_id,
                performance_mode=request_performance_mode(request.performance_mode),
                selected_model=request.selected_model,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"News digest failed: {exc}") from exc


@router.post("/news/runs/{run_id}/discuss", response_model=NewsRunResponse)
def discuss_news_run_endpoint(
    run_id: str,
    request: NewsRunDiscussRequest,
    service: NewsServiceDependency,
) -> NewsRunResponse:
    validate_choice(request.selected_model, MODEL_OPTIONS, "selected_model")
    validate_choice(request.relationship_mode, ATMOS_OPTIONS, "relationship_mode")
    try:
        return _response(
            service.discuss(
                run_id,
                group_thread_id=request.group_thread_id,
                interaction_mode=request.relationship_mode,
                performance_mode=request_performance_mode(request.performance_mode),
                selected_model=request.selected_model,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"News discuss failed: {exc}") from exc


@router.post("/news/lookup", response_model=NewsLookupResponse)
def lookup_news_endpoint(request: NewsLookupRequest) -> NewsLookupResponse:
    from src.api import fetch_news_items, format_news_source_block, get_last_feed_warnings

    try:
        news_items = fetch_news_items(
            query_text=request.query,
            max_items=request.max_items,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"News lookup failed: {exc}") from exc
    return NewsLookupResponse(
        query_text=request.query,
        news_items=news_items,
        source_block=format_news_source_block(request.query, news_items),
        warnings=get_last_feed_warnings(),
    )


@router.post("/news/round", response_model=NewsSearchResponse)
def run_news_round_endpoint(request: NewsSearchRequest) -> NewsSearchResponse:
    del request
    raise HTTPException(status_code=410, detail="Use POST /news/runs")


@router.post("/wechat/news-round", response_model=NewsSearchResponse)
def wechat_news_round_endpoint(request: NewsSearchRequest) -> NewsSearchResponse:
    return run_news_round_endpoint(request)


@router.post("/news/search", response_model=NewsStageSearchResponse)
def search_news_stage_endpoint(request: NewsStageSearchRequest) -> NewsStageSearchResponse:
    del request
    raise HTTPException(status_code=410, detail="Use POST /news/runs")


@router.post("/news/enrich", response_model=NewsEnrichResponse)
def enrich_news_stage_endpoint(request: NewsEnrichRequest) -> NewsEnrichResponse:
    del request
    raise HTTPException(status_code=410, detail="Use POST /news/runs/{id}/enrich")


@router.post("/news/digest", response_model=NewsDigestResponse)
def digest_news_stage_endpoint(request: NewsDigestRequest) -> NewsDigestResponse:
    del request
    raise HTTPException(status_code=410, detail="Use POST /news/runs/{id}/digest")


@router.post("/news/discuss", response_model=NewsDiscussResponse)
def discuss_news_stage_endpoint(request: NewsDiscussRequest) -> NewsDiscussResponse:
    del request
    raise HTTPException(status_code=410, detail="Use POST /news/runs/{id}/discuss")
