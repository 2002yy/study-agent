"""Four synthetic L5 controls; reader usability never grants publication authority."""
import hashlib
import time

import pytest

from src.news.article_fetcher import ArticleReadResult
from src.web import tool_gateway
from src.web.research import official_resolver as resolver
from src.web.research_recovery import recover_public_research, recovery_summary
from src.web.tool_evidence import evidence_tool_calls
from tests.test_lookup_tier_qualification import saved_exit


QUERY = "Python 3.14什么时候发布"
CASES = {
    "alternate_official": [("https://docs.python.org/3.14/whatsnew/3.14.html",
                            "Python 3.14 release date: October 7, 2025.")],
    "nonofficial_direct": [("https://realpython.com/python314-release/",
                            "Python 3.14 release date: October 7, 2025.")],
    "related_missing_field": [("https://docs.python.org/3.14/tutorial/index.html",
                              "Python 3.14 tutorial. This page explains the language.")],
    "unbound_exhaustion": [("https://docs.python.org/3.13/whatsnew/index.html",
                            "Python 3.13 release information."),
                           ("https://docs.python.org/3.15/whatsnew/index.html",
                            "Python 3.15 release information.")],
}


@pytest.mark.parametrize("case_id", CASES)
def test_rescue_usability_and_claim_publication_are_separate(monkeypatch, tmp_path, case_id):
    backend_reads = []

    class UnavailableOfficial:
        def open(self, request, timeout):
            backend_reads.append(request.full_url)
            raise TimeoutError("synthetic official transport timeout")

    monkeypatch.setattr(resolver, "build_opener", lambda *_a: UnavailableOfficial())
    bodies = dict(CASES[case_id])

    def reader(url, **_kwargs):
        backend_reads.append(url)
        return ArticleReadResult(ok=True, requested_url=url, final_url=url,
                                 text=bodies[url], method="synthetic_frozen_reader")

    monkeypatch.setattr(tool_gateway, "fetch_article_read_result", reader)
    gateway = tool_gateway.GeneralWebGateway()
    searches = []

    def search(query, **_kwargs):
        searches.append(query)
        return {"status": "ok", "results": [
            {"url": url, "title": "Python 3.14 release", "snippet": "candidate only"}
            for url in bodies
        ]}

    monkeypatch.setattr(gateway, "search_exact", search)
    started = time.monotonic()
    calls = recover_public_research(gateway, QUERY)
    elapsed = time.monotonic() - started
    summary = recovery_summary(calls)
    assert searches and len(searches) <= 2
    assert summary["mode"] == "lookup" and 2 <= summary["reads"] <= 3
    assert len(backend_reads) == summary["reads"]
    assert backend_reads[0] == resolver.official_plan(QUERY).urls[0]
    assert elapsed < 30
    if case_id != "unbound_exhaustion":
        assert summary["status"] == "read_backed" and evidence_tool_calls(calls)
    else:
        assert summary["reads"] == 3 and not evidence_tool_calls(calls)
    _, audit = saved_exit(tmp_path, QUERY, calls)
    assert audit["status"] == "abstained" and not audit["assertion_refs"]
    assert audit["answer_generation_calls"] == 0
    for call in calls:
        if call["name"] == "web_read" and call["result"].get("ok"):
            read = call["result"]
            assert read["content_sha256"] == hashlib.sha256(read["content"].encode()).hexdigest()
            assert "official_fields" not in read
