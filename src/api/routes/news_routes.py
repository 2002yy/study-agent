"""News endpoints — search, enrich, digest, discuss, lookup."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.models.news import (
    NewsDigestRequest,
    NewsDigestResponse,
    NewsDiscussRequest,
    NewsDiscussResponse,
    NewsEnrichRequest,
    NewsEnrichResponse,
    NewsLookupRequest,
    NewsLookupResponse,
    NewsSearchRequest,
    NewsSearchResponse,
    NewsStageSearchRequest,
    NewsStageSearchResponse,
)
from src.constants import ATMOS_OPTIONS, MODEL_OPTIONS

router = APIRouter(tags=["news"])


@router.post("/news/round", response_model=NewsSearchResponse)
def run_news_round_endpoint(request: NewsSearchRequest) -> NewsSearchResponse:
    from src.api import init_session, load_runtime_modes, news_result_payload, request_performance_mode, run_news_round, validate_choice
    from src.wechat_service import RuntimeContext

    runtime_modes = load_runtime_modes()
    performance_mode = request_performance_mode(request.performance_mode)
    validate_choice(request.selected_model, MODEL_OPTIONS, "selected_model")
    validate_choice(request.relationship_mode, ATMOS_OPTIONS, "relationship_mode")
    session_id = request.session_id or init_session()
    result = run_news_round(
        query_text=request.query,
        read_articles=request.read_articles,
        runtime_context=RuntimeContext(
            performance_mode=performance_mode,
            selected_model=request.selected_model,
            interaction_mode=request.relationship_mode,
            session_id=session_id,
            safe_mode=runtime_modes.safe_mode,
            memory_mode=runtime_modes.memory_mode,
            route_mode=runtime_modes.route_mode,
        ),
    )
    return news_result_payload(result, session_id)


@router.post("/news/search", response_model=NewsStageSearchResponse)
def search_news_stage_endpoint(request: NewsStageSearchRequest) -> NewsStageSearchResponse:
    from src.api import run_search_stage

    items = run_search_stage(request.query, max_items=request.max_items)
    return NewsStageSearchResponse(query_text=request.query, news_items=items)


@router.post("/news/enrich", response_model=NewsEnrichResponse)
def enrich_news_stage_endpoint(request: NewsEnrichRequest) -> NewsEnrichResponse:
    from src.api import load_runtime_modes, run_enrich_stage

    runtime_modes = load_runtime_modes()
    profile = runtime_modes.profile
    safe = (
        request.safe_mode
        if request.safe_mode is not None
        else profile.safe_mode
    )
    if safe:
        return NewsEnrichResponse(
            query_text=request.query_text,
            news_items=request.news_items,
            skipped=True,
            skipped_reason="safe_mode",
        )
    if not profile.allow_article_network_read:
        return NewsEnrichResponse(
            query_text=request.query_text,
            news_items=request.news_items,
            skipped=True,
            skipped_reason=profile.article_network_read_reason,
        )
    items = run_enrich_stage(
        request.news_items,
        max_articles=request.max_articles,
        query_text=request.query_text,
        max_chars_per_article=request.max_chars_per_article,
    )
    return NewsEnrichResponse(query_text=request.query_text, news_items=items)


@router.post("/news/digest", response_model=NewsDigestResponse)
def digest_news_stage_endpoint(request: NewsDigestRequest) -> NewsDigestResponse:
    from src.api import request_performance_mode, run_digest_stage, validate_choice

    validate_choice(request.selected_model, MODEL_OPTIONS, "selected_model")
    performance_mode = request_performance_mode(request.performance_mode)
    digest, source_block, article_coverage, warnings = run_digest_stage(
        request.news_items,
        query_text=request.query_text,
        performance_mode=performance_mode,
        selected_model=request.selected_model,
    )
    return NewsDigestResponse(
        query_text=request.query_text,
        digest=digest,
        source_block=source_block,
        article_coverage=article_coverage,
        warnings=warnings,
    )


@router.post("/news/discuss", response_model=NewsDiscussResponse)
def discuss_news_stage_endpoint(request: NewsDiscussRequest) -> NewsDiscussResponse:
    from src.api import init_session, request_performance_mode, run_discussion_stage, validate_choice

    validate_choice(request.selected_model, MODEL_OPTIONS, "selected_model")
    validate_choice(request.relationship_mode, ATMOS_OPTIONS, "relationship_mode")
    performance_mode = request_performance_mode(request.performance_mode)
    session_id = request.session_id or init_session()
    discussion, group_content = run_discussion_stage(
        request.digest,
        interaction_mode=request.relationship_mode,
        performance_mode=performance_mode,
        selected_model=request.selected_model,
        source_block=request.source_block,
        session_id=session_id,
    )
    return NewsDiscussResponse(discussion=discussion, group_content=group_content, session_id=session_id)


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


@router.post("/wechat/news-round", response_model=NewsSearchResponse)
def wechat_news_round_endpoint(request: NewsSearchRequest) -> NewsSearchResponse:
    return run_news_round_endpoint(request)
