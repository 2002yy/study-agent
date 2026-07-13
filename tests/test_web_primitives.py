from __future__ import annotations

from datetime import datetime, timezone
import time

from src.web.concurrency import BoundedTask, run_bounded
from src.web.models import parse_published_at
from src.web.orchestrator import build_search_plan
from src.web.query_router import SearchIntent, route_query
from src.web.security import validate_service_endpoint


def test_parse_published_at_normalizes_provider_dates_to_utc():
    parsed = parse_published_at("2026-06-30T12:34:56+08:00")

    assert parsed is not None
    assert parsed.isoformat() == "2026-06-30T04:34:56+00:00"


def test_service_endpoint_policy_separates_loopback_from_public_targets():
    assert validate_service_endpoint("https://search.example.com")
    assert not validate_service_endpoint("http://127.0.0.1:8080")
    assert validate_service_endpoint(
        "http://127.0.0.1:8080",
        allow_loopback=True,
    )
    assert not validate_service_endpoint(
        "http://169.254.169.254/latest/meta-data",
        allow_loopback=True,
    )


def test_bounded_runner_returns_at_deadline_without_waiting_for_slow_task():
    started = time.perf_counter()
    outcomes = run_bounded(
        [
            BoundedTask("fast", lambda: "ok"),
            BoundedTask("slow", lambda: time.sleep(0.5)),
        ],
        concurrency=2,
        total_timeout=0.05,
    )

    assert time.perf_counter() - started < 0.3
    assert outcomes[0].value == "ok"
    assert outcomes[1].timed_out is True


def test_query_router_separates_news_technical_and_direct_url():
    assert route_query("OpenAI 最新新闻") == SearchIntent.NEWS
    assert route_query("Godot API 报错") == SearchIntent.TECHNICAL
    assert route_query("https://docs.python.org/3/") == SearchIntent.DIRECT_URL
    assert build_search_plan("Godot API 报错").searxng_categories == "general"


def test_search_plan_carries_normalized_query_and_as_of_date():
    plan = build_search_plan(
        "gpt5.6sol 最新进展",
        now=datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc),
    )

    assert plan.canonical_query == "GPT-5.6 Sol 最新进展"
    assert plan.query_variants[0] == "GPT-5.6 Sol 最新进展"
    assert plan.as_of_date == "2026-07-13"
    assert plan.freshness_days == 30
    assert plan.intent == SearchIntent.NEWS
