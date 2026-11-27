"""Answer evidence is narrower than reading: only traceable sources are admitted."""

from __future__ import annotations

from src.tools.web_agent import WebToolTrace
from src.web.tool_evidence import admit_tool_evidence, evidence_tool_calls


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
