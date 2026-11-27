"""Answer evidence is allocated per source, not cut at a global prefix."""

from __future__ import annotations

from src.tools.web_agent import WebToolTrace
from src.web.answer_evidence import assemble_answer_evidence


def _read(url: str, body: str, *, title: str = "") -> dict:
    return {
        "name": "web_read",
        "arguments": {"url": url},
        "result": {
            "ok": True,
            "status": "read",
            "url": url,
            "title": title or url,
            "content": body,
            "method": "read",
        },
    }


def _page(name: str, *, paragraphs: int = 120, key: str = "") -> str:
    lines = [
        f"{name} 第{index}段：这是一段测试正文，说明背景信息与细节。"
        for index in range(paragraphs)
    ]
    if key:
        lines[paragraphs // 2] = key
    return "\n".join(lines)


def test_the_last_long_source_is_not_dropped_by_the_first_two():
    calls = [
        _read("https://a.example/1", _page("A")),
        _read("https://b.example/2", _page("B")),
        _read(
            "https://c.example/3",
            _page("C", key="最后指出 alpha 方案的反例与限制，不可忽略。"),
        ),
    ]

    block = assemble_answer_evidence(
        calls, query="alpha 与 beta 的机制", limit=9000
    )

    assert len(block) <= 9000
    assert all(host in block for host in ("a.example", "b.example", "c.example"))
    assert "反例与限制" in block


def test_a_short_source_keeps_its_whole_body_before_long_ones_share():
    short = "短页开头。\n" + ("短页正文内容。" * 40) + "\n短页结尾标记ALPHAEND。"
    calls = [
        _read("https://short.example/s", short),
        _read("https://long.example/1", _page("L1", paragraphs=400)),
        _read("https://long.example/2", _page("L2", paragraphs=400)),
    ]

    block = assemble_answer_evidence(calls, query="alpha", limit=12000)

    assert len(block) <= 12000
    assert "短页结尾标记ALPHAEND" in block
    assert "L1 第350段" not in block  # a long page is trimmed, the short one is not
    assert "long.example/1" in block and "long.example/2" in block


def test_identical_bodies_spend_the_budget_once():
    shared = _page("S", paragraphs=300, key="重复正文中的 alpha 结论。")
    calls = [
        _read("https://one.example/doc", shared),
        _read("https://mirror.example/doc", shared),
        _read(
            "https://other.example/doc",
            _page("O", paragraphs=300, key="另一个来源的 beta 反例。"),
        ),
    ]

    block = assemble_answer_evidence(calls, query="alpha beta", limit=9000)

    assert len(block) <= 9000
    assert "正文与来源 1 相同" in block
    assert "beta 反例" in block


def test_head_and_tail_survive_a_page_without_matching_terms():
    body = "\n".join(
        ["开头定义：这一页先给出背景。"]
        + [f"中段 {index}：普通说明文字，不含任何关键词。" for index in range(300)]
        + ["结论在最后：最后一段仍然保留。"],
    )
    calls = [_read("https://plain.example/doc", body)]

    block = assemble_answer_evidence(calls, query="完全无关的问题", limit=3000)

    assert len(block) <= 3000
    assert "开头定义" in block
    assert "结论在最后" in block


def test_cross_language_page_fills_space_in_document_order():
    body = "\n".join(
        f"Section {index}: the article explains concurrency and locking in detail."
        for index in range(80)
    )
    calls = [_read("https://en.example/doc", body)]

    block = assemble_answer_evidence(calls, query="如何避免死锁", limit=4000)

    assert len(block) <= 4000
    assert "Section 40" in block


def _search(urls: list[str]) -> dict:
    return {
        "name": "web_search",
        "arguments": {"query": "alpha"},
        "result": {
            "status": "ok",
            "results": [{"title": url, "url": url} for url in urls],
        },
    }


def test_context_block_uses_the_query_and_keeps_every_admitted_url():
    reads = [
        _read(f"https://source.example/{index}", _page(f"S{index}"))
        for index in range(1, 4)
    ]
    trace = WebToolTrace(
        calls=(_search([row["result"]["url"] for row in reads]), *reads),
        query="alpha 机制",
    )

    block = trace.context_block()

    assert len(block) <= 30000
    assert all(f"source.example/{index}" in block for index in range(1, 4))


def test_trace_keeps_the_raw_bodies_that_the_block_compressed(monkeypatch):
    monkeypatch.setenv("WEB_TOOL_CONTEXT_MAX_CHARS", "5000")
    body = _page("R", paragraphs=300, key="alpha 原始正文。")
    url = "https://raw.example/doc"
    read = _read(url, body)
    trace = WebToolTrace(
        calls=(_search([url]), read), query="alpha", evidence_calls=(read,)
    )

    block = trace.context_block()
    stored = next(
        call["result"]["content"]
        for call in trace.to_dict()["calls"]
        if call["name"] == "web_read"
    )

    assert len(block) < len(stored)
    assert stored == body


def test_block_never_exceeds_its_limit_even_with_many_headers():
    calls = [
        _read(
            f"https://source-{index}.example/{'x' * 60}",
            _page(f"S{index}", paragraphs=80),
        )
        for index in range(8)
    ]

    block = assemble_answer_evidence(calls, query="alpha", limit=1000)

    assert len(block) <= 1000
