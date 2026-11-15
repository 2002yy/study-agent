"""An answer may cite only pages the turn actually read."""

from __future__ import annotations

from src.domain.answer_links import outside_evidence_links


def test_a_link_to_an_unread_page_is_outside_the_evidence():
    answer = "结论见 [WAL](https://www.sqlite.org/wal.html)。"
    evidence = ["https://www.postgresql.org/docs/8.1/runtime-config-wal.html"]

    assert outside_evidence_links(answer, evidence) == [
        "https://www.sqlite.org/wal.html"
    ]


def test_a_read_page_is_allowed_with_normal_url_variation():
    answer = (
        "见 [WAL](https://sqlite.org/wal.html) 与 "
        "https://www.sqlite.org/wal.html?utm_source=x"
    )
    evidence = ["https://www.sqlite.org/wal.html"]

    assert outside_evidence_links(answer, evidence) == []


def test_a_mix_of_read_and_unread_links_reports_only_the_unread():
    answer = (
        "见 [WAL](https://www.sqlite.org/wal.html) 和 "
        "[博客](https://example.org/post)。"
    )
    evidence = ["https://sqlite.org/wal.html"]

    assert outside_evidence_links(answer, evidence) == ["https://example.org/post"]


def test_no_links_means_nothing_to_reject():
    assert outside_evidence_links("WAL 允许读写并发，但只有一个写者。", []) == []
