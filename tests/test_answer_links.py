"""An answer may cite only pages the turn actually read."""

from __future__ import annotations

from src.domain.answer_links import (
    classify_outside_links,
    outside_evidence_links,
    strip_outside_links,
)


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


def test_an_unread_page_on_a_read_host_is_a_coverage_gap():
    """backup.html may well exist; this turn simply never read it."""

    classified = classify_outside_links(
        "见 [备份](https://www.sqlite.org/backup.html)",
        ["https://www.sqlite.org/wal.html"],
    )
    assert classified == [{
        "url": "https://www.sqlite.org/backup.html",
        "kind": "read_host_page_not_read",
    }]


def test_a_host_nobody_read_is_reported_separately():
    classified = classify_outside_links(
        "见 [博客](https://example.org/post)",
        ["https://www.sqlite.org/wal.html"],
    )
    assert classified == [{
        "url": "https://example.org/post",
        "kind": "host_not_in_evidence",
    }]


def test_a_different_document_query_is_not_a_read_page():
    assert outside_evidence_links(
        "见 [问题二](https://forum.example/thread?id=2)",
        ["https://forum.example/thread?id=1"],
    ) == ["https://forum.example/thread?id=2"]


def test_a_different_port_is_not_the_same_read_page():
    assert outside_evidence_links(
        "见 https://forum.example:8443/thread",
        ["https://forum.example/thread"],
    ) == ["https://forum.example:8443/thread"]


def test_strip_removes_an_unread_markdown_link_but_keeps_the_claim():
    answer = "请看[备份](https://official.example/backup)中的说明。"
    evidence = ["https://official.example/release"]

    cleaned, removed = strip_outside_links(answer, evidence)

    assert "https://official.example/backup" not in cleaned
    assert "请看备份中的说明。" in cleaned
    assert removed == ["https://official.example/backup"]


def test_strip_keeps_a_read_link_and_a_descriptive_label():
    answer = (
        "结论[来源](https://bad.example/a)与"
        "[官方 README](https://official.example/release)。"
    )
    evidence = ["https://official.example/release"]

    cleaned, removed = strip_outside_links(answer, evidence)

    assert cleaned == "结论与[官方 README](https://official.example/release)。"
    assert removed == ["https://bad.example/a"]


def test_strip_removes_a_bare_unread_url():
    answer = "裸链 https://bad.example/x 和好链 https://official.example/release"
    evidence = ["https://official.example/release"]

    cleaned, removed = strip_outside_links(answer, evidence)

    assert "https://bad.example/x" not in cleaned
    assert "https://official.example/release" in cleaned
    assert removed == ["https://bad.example/x"]
