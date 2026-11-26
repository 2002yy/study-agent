"""Offline contract: SearXNG failure is not a healthy empty result."""

import json
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from src.news.search_sources import searxng_source
from src.web.tool_gateway import GeneralWebGateway


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int):
        return self.payload


class SearxngObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "WEB_ENABLE_SEARXNG": "1",
            "SEARXNG_BASE_URL": "https://search.example.com",
            "WEB_ENABLE_BING_RSS": "0",
            "WEB_ENABLE_DUCKDUCKGO": "0",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_stopped_container_is_a_provider_failure_not_no_results(self):
        with patch.object(searxng_source, "urlopen", side_effect=ConnectionRefusedError("container stopped")) as fetch:
            result = GeneralWebGateway(search_strategy="fallback").search_exact("SQLite backup")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "providers_failed")
        self.assertEqual(result["provider_outcomes"][0]["status"], "failed")
        self.assertEqual(result["provider_outcomes"][0]["reason"], "connection_failed")
        self.assertTrue(any("ConnectionRefusedError" in text for text in result["provider_errors"]))

    def test_healthy_empty_result_stays_empty_without_error(self):
        with patch.object(searxng_source, "urlopen", return_value=_Response(b'{"results":[]}')):
            result = GeneralWebGateway(search_strategy="fallback").search_exact("SQLite backup")
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["reason"], "providers_returned_no_results")
        self.assertEqual(result["provider_outcomes"][0]["status"], "empty")
        self.assertEqual(result["provider_errors"], [])

    def test_failed_searxng_and_empty_fallback_remain_distinguishable(self):
        with patch.dict(os.environ, {"WEB_ENABLE_BING_RSS": "1"}), (
            patch.object(searxng_source, "urlopen", side_effect=ConnectionRefusedError("offline"))
        ), patch.object(GeneralWebGateway, "_search_bing_rss", return_value=([], "")):
            result = GeneralWebGateway(search_strategy="fallback").search_exact("SQLite backup")
        self.assertEqual(result["status"], "empty")  # stable gateway contract
        self.assertEqual(result["reason"], "providers_returned_no_results")
        self.assertEqual([row["status"] for row in result["provider_outcomes"][:2]], ["failed", "empty"])

    def test_successful_fallback_keeps_original_provider_failure_auditable(self):
        row = {"title": "Backup API", "url": "https://sqlite.org/backup.html"}
        with patch.dict(os.environ, {"WEB_ENABLE_BING_RSS": "1"}), (
            patch.object(searxng_source, "urlopen", side_effect=ConnectionRefusedError("offline"))
        ), patch.object(GeneralWebGateway, "_search_bing_rss", return_value=([row], "")):
            result = GeneralWebGateway(search_strategy="fallback").search_exact("SQLite backup")
        self.assertEqual(result["status"], "ok")
        self.assertEqual([row["status"] for row in result["provider_outcomes"][:2]], ["failed", "ok"])
        self.assertEqual(len(result["results"]), 1)

    def test_invalid_json_is_not_counted_as_a_valid_empty_search(self):
        with patch.object(searxng_source, "urlopen", return_value=_Response(b'{"results":')):
            result = GeneralWebGateway(search_strategy="fallback").search_exact("SQLite backup")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["provider_outcomes"][0]["reason"], "invalid_json")

    def test_malformed_json_shape_is_diagnostic_not_a_crash(self):
        with patch.object(searxng_source, "urlopen", return_value=_Response(json.dumps([]).encode())):
            result = GeneralWebGateway(search_strategy="fallback").search_exact("SQLite backup")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["provider_outcomes"][0]["reason"], "invalid_json")

    def test_detailed_search_keeps_provider_failure_diagnostics(self):
        with patch.dict(os.environ, {"WEB_ENABLE_BING_RSS": "1"}), (
            patch.object(searxng_source, "urlopen", side_effect=ConnectionRefusedError("offline"))
        ), patch.object(GeneralWebGateway, "_search_bing_rss", return_value=([], "")):
            result = GeneralWebGateway(search_strategy="fallback").search_detailed("SQLite backup")
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["reason"], "providers_returned_no_results")
        self.assertTrue(any(row["status"] == "failed" for row in result["provider_outcomes"]))

    def test_news_worker_captures_its_own_error_before_join(self):
        from src.news import rss_fetcher

        def failure_in_worker(*_args, **_kwargs):
            searxng_source._set_last_error("ConnectionRefusedError: container stopped")
            return []

        with patch.object(rss_fetcher, "registered_feed_urls", return_value=[]), (
            patch.object(rss_fetcher, "search_searxng", side_effect=failure_in_worker)
        ):
            result = rss_fetcher._fetch_query_news_items("SQLite backup")
        self.assertEqual(result, [])
        warnings = rss_fetcher.get_last_feed_warnings()
        self.assertTrue(any("ConnectionRefusedError" in row["message"] for row in warnings))

    def test_parallel_searches_do_not_share_last_error(self):
        barrier = threading.Barrier(2)

        def response(req, timeout):
            query = parse_qs(urlsplit(req.full_url).query)["q"][0]
            barrier.wait(timeout=2)
            if query == "failed":
                raise ConnectionRefusedError("container stopped")
            return _Response(b'{"results":[]}')

        def search(query):
            rows = searxng_source.search_searxng(query)
            return rows, searxng_source.get_last_searxng_error()

        with patch.object(searxng_source, "urlopen", side_effect=response), ThreadPoolExecutor(max_workers=2) as pool:
            failed = pool.submit(search, "failed")
            empty = pool.submit(search, "empty")
            failure_rows, failure_error = failed.result(timeout=3)
            empty_rows, empty_error = empty.result(timeout=3)
        self.assertEqual(failure_rows, empty_rows)
        self.assertIn("ConnectionRefusedError", failure_error)
        self.assertEqual(empty_error, "")


if __name__ == "__main__":
    unittest.main()
