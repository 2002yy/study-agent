"""Completion judgment: a text-only stop is not proof the task is done."""

from __future__ import annotations

from src.tools.web_agent import research_completion_gap


def _search(query: str, urls: list[str]) -> dict:
    return {
        "name": "web_search",
        "arguments": {"query": query},
        "result": {
            "status": "ok",
            "results": [
                {"title": f"source {index}", "url": url}
                for index, url in enumerate(urls)
            ],
        },
    }


def _read(url: str, *, ok: bool = True, content: str = "x" * 1200, **extra) -> dict:
    if ok:
        result = {"ok": True, "url": url, "content": content, "kind": "web_page"}
        result.update(extra)
        return {"name": "web_read", "arguments": {"url": url}, "result": result}
    return {
        "name": "web_read",
        "arguments": {"url": url},
        "result": {
            "ok": False,
            "url": url,
            "error": extra.get("error", "read_failed"),
            "error_code": extra.get("error_code", "read_failed"),
        },
    }


def test_a_text_only_first_reply_without_any_tool_is_not_completion() -> None:
    message = research_completion_gap([], "I think the answer is 42.", "stop")
    assert message is not None
    assert "web_search" in message
    assert "memory" in message


def test_an_empty_or_truncated_reply_is_continued() -> None:
    assert research_completion_gap([], "", "stop") is not None
    message = research_completion_gap([_read("https://a.example")], "partial", "length")
    assert message is not None
    assert "cut off" in message


def test_zero_result_search_is_not_proof_of_nonexistence() -> None:
    message = research_completion_gap(
        [_search("obscure thing", [])], "I could not find anything.", "stop"
    )
    assert message is not None
    assert "zero results" in message
    assert "platform" in message


def test_found_candidates_but_read_nothing_is_continued() -> None:
    message = research_completion_gap(
        [_search("godot jolt", ["https://docs.example/jolt"])],
        "I could not find the information.",
        "stop",
    )
    assert message is not None
    assert "https://docs.example/jolt" in message
    assert "have not read" in message


def test_all_reads_failed_points_to_browse_not_to_giving_up() -> None:
    message = research_completion_gap(
        [_read("https://a.example", ok=False, error_code="403")],
        "The site is unavailable.",
        "stop",
    )
    assert message is not None
    assert 'mode="browse"' in message
    assert "not a failed research task" in message


def test_a_missing_claim_with_unread_candidates_is_continued() -> None:
    message = research_completion_gap(
        [
            _search("release notes", ["https://official.example/release"]),
            _read("https://other.example/page"),
        ],
        "资料不足，无法确认该版本。",
        "stop",
    )
    assert message is not None
    assert "https://official.example/release" in message
    assert "never read" in message


def test_a_shell_or_short_read_is_an_extraction_failure() -> None:
    message = research_completion_gap(
        [_read("https://a.example", content="Please enable JavaScript to continue.")],
        "The page did not contain the answer.",
        "stop",
    )
    assert message is not None
    assert "extraction failure" in message
    assert 'mode="browse"' in message


def test_one_adequate_read_accepts_a_confident_answer_even_with_unread_candidates() -> None:
    evidence = [
        _search("q", ["https://one.example", "https://two.example"]),
        _read("https://one.example", content="A complete article body. " * 80),
    ]
    assert research_completion_gap(evidence, "The answer is X.", "stop") is None


def test_video_or_audio_reads_are_not_judged_as_short_pages() -> None:
    reading = _read(
        "https://video.example/watch",
        content="short transcript",
        kind="video",
    )
    assert research_completion_gap([reading], "The video says X.", "stop") is None
