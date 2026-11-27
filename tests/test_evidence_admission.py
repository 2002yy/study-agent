"""Answer evidence is narrower than reading: only traceable sources are admitted."""

from __future__ import annotations

from src.tools.web_agent import WebToolTrace
from src.web.tool_evidence import (
    admit_tool_evidence,
    evidence_tool_calls,
    exploration_read_records,
)


def _read(url: str, *, ok: bool = True, links=()) -> dict:
    return {
        "name": "web_read",
        "arguments": {"url": url},
        "result": {
            "ok": ok,
            "url": url,
            "content": "body" if ok else "",
            "links": list(links),
        },
    }


def _search(urls: list[str]) -> dict:
    return {
        "name": "web_search",
        "arguments": {"query": "q"},
        "result": {
            "status": "ok",
            "results": [{"title": url, "url": url} for url in urls],
        },
    }


def test_user_supplied_url_is_admitted_without_a_search():
    url = "https://user.example/doc"
    admitted, rejected = admit_tool_evidence(
        [_read(url)], user_urls=[url]
    )

    assert len(admitted) == 1
    assert rejected == []


def test_search_discovered_and_anchor_urls_are_admitted():
    base = "https://docs.example.org/guide"
    calls = [_search([base]), _read(base + "#section")]

    admitted, rejected = admit_tool_evidence(calls)

    assert len(admitted) == 1
    assert rejected == []


def test_citation_link_from_an_admitted_read_is_admitted_on_read():
    source = "https://docs.example.org/a"
    cited = "https://paper.example/b"
    calls = [
        _search([source]),
        _read(source, links=[{"title": "paper", "url": cited}]),
        _read(cited),
    ]

    admitted, rejected = admit_tool_evidence(calls)

    assert [call["result"]["url"] for call in admitted] == [source, cited]
    assert rejected == []


def test_unestablished_and_failed_reads_are_rejected_with_reasons():
    calls = [_read("https://random.example/x"), _read("https://dead.example/y", ok=False)]

    admitted, rejected = admit_tool_evidence(calls)

    assert admitted == []
    assert [row["reason"] for row in rejected] == [
        "source_not_established",
        "read_failed",
    ]


def test_trace_context_uses_only_admitted_calls():
    admitted_read = _read("https://docs.example.org/a")
    rejected_read = _read("https://random.example/x")
    search = _search(["https://docs.example.org/a"])
    admitted, rejected = admit_tool_evidence([search, admitted_read, rejected_read])
    trace = WebToolTrace(
        calls=(search, admitted_read, rejected_read),
        evidence_calls=tuple(admitted),
        rejected_evidence=tuple(rejected),
    )

    block = trace.context_block()
    assert "docs.example.org/a" in block
    assert "random.example/x" not in block
    assert trace.to_dict()["rejected_evidence"] == [
        {"url": "https://random.example/x", "reason": "source_not_established"}
    ]
    assert trace.used is True


def test_legacy_trace_without_admission_keeps_derived_evidence():
    search = _search(["https://docs.example.org/a"])
    read = _read("https://docs.example.org/a")
    trace = WebToolTrace(calls=(search, read))

    assert trace.evidence_calls is None
    assert trace.admitted_calls() == evidence_tool_calls([search, read])


def _failed_read(url: str) -> dict:
    return {
        "name": "web_read",
        "arguments": {"url": url},
        "result": {"ok": False, "url": url, "error": "timeout"},
    }


def test_failed_attempt_at_an_admitted_url_keeps_its_rejection():
    url = "https://docs.example.org/a"
    calls = [_search([url]), _failed_read(url), _read(url)]

    admitted, rejected = admit_tool_evidence(calls)

    assert [call["result"]["url"] for call in admitted] == [url]
    assert rejected == [{"url": url, "reason": "read_failed"}]


def test_repeated_successful_reads_are_all_admitted_once_each():
    url = "https://docs.example.org/a"
    calls = [_search([url]), _read(url), _read(url)]

    admitted, rejected = admit_tool_evidence(calls)

    assert len(admitted) == 2
    assert rejected == []


def test_exploratory_read_bodies_are_recorded_without_becoming_evidence():
    admitted_url = "https://docs.example.org/a"
    explored_url = "https://random.example/x"
    calls = [
        _search([admitted_url]),
        _read(admitted_url),
        _read(explored_url),
        _failed_read("https://dead.example/y"),
    ]

    admitted, rejected = admit_tool_evidence(calls)
    records = exploration_read_records(calls)

    assert [call["result"]["url"] for call in admitted] == [admitted_url]
    assert [row["url"] for row in rejected] == [
        explored_url,
        "https://dead.example/y",
    ]
    assert [row["url"] for row in records] == [explored_url]
    assert records[0]["content"] == "body"
    assert records[0]["chars"] == 4
    assert records[0]["truncated"] is False
    assert records[0]["reason"] == "source_not_established"
    assert len(records[0]["digest"]) == 12


def test_exploratory_body_storage_is_bounded_and_reports_truncation():
    urls = [f"https://random.example/{index}" for index in range(3)]
    calls = [_read(url) for url in urls]

    records = exploration_read_records(calls, content_chars=2, total_chars=4)

    assert len(records) == 2
    assert all(row["truncated"] is True for row in records)
    assert [row["stored_chars"] for row in records] == [2, 2]
    assert all(row["chars"] == 4 for row in records)


def test_discovery_is_still_required_by_default():
    call = _read("https://docs.example.org/en/latest/guide")

    admitted, rejected = admit_tool_evidence([call])

    assert admitted == []
    assert rejected == [
        {"url": "https://docs.example.org/en/latest/guide", "reason": "source_not_established"}
    ]


def test_relaxed_admission_takes_a_successful_public_read_without_a_search():
    call = _read("https://docs.example.org/en/latest/guide")

    admitted, rejected = admit_tool_evidence([call], require_discovery=False)

    assert [row["result"]["url"] for row in admitted] == [
        "https://docs.example.org/en/latest/guide"
    ]
    assert rejected == []


def test_relaxed_admission_still_rejects_ineligible_failed_and_empty_reads():
    ineligible = _read("https://docs.example.org/a")
    ineligible["result"]["answer_eligible"] = False
    empty = _read("https://docs.example.org/b")
    empty["result"]["content"] = "  "
    failed = _failed_read("https://docs.example.org/c")

    admitted, rejected = admit_tool_evidence(
        [ineligible, empty, failed], require_discovery=False
    )

    assert admitted == []
    assert [row["reason"] for row in rejected] == [
        "source_not_established",
        "empty_content",
        "read_failed",
    ]


def test_relaxed_admission_rejects_a_non_public_url():
    call = _read("http://127.0.0.1/admin")

    admitted, rejected = admit_tool_evidence([call], require_discovery=False)

    assert admitted == []
    assert rejected == [{"url": "", "reason": "non_public_url"}]
