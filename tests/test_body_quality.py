"""Body eligibility: a page is judged by structure and type, never by a length threshold."""

from __future__ import annotations

from src.web.link_discovery import classify_body

NAV_SHELL = "\n".join(f"{i}. Section title | v1.{i}" for i in range(30))
TOC_NO_NUMBERS = "\n".join("Getting started\nInstallation\nConfiguration\nBackup"
                           for _ in range(4))
CN_ARTICLE = ("多版本并发控制通过保留旧版本行来实现一致性：因为每个事务读取自己的快照，"
              "读操作不会阻塞写操作。代价是旧版本必须清理，否则会造成表膨胀。"
              "系统需要定期回收不再可见的行版本，否则查询会逐渐变慢。")
EN_ARTICLE = ("PostgreSQL uses multiversion concurrency control so each transaction reads a "
              "snapshot. Readers never block writers, and writers never block readers, "
              "because an update creates a new row version. The main cost is that old row "
              "versions must be cleaned up or the table will bloat over time.")


def test_index_shell_is_navigation() -> None:
    kind, evidence = classify_body(NAV_SHELL)
    assert kind == "navigation"
    assert evidence["looks_like_navigation"] is True
    assert evidence["reason"] == "link_farm"


def test_short_real_answer_is_substantive_not_rejected_by_length() -> None:
    """The article is short; a length threshold would have thrown it away."""
    kind, evidence = classify_body(CN_ARTICLE)
    assert len(CN_ARTICLE) < 260
    assert kind == "substantive"
    assert evidence["reason"] == "prose_sentences"


def test_english_article_counts_for_a_chinese_goal() -> None:
    kind, _ = classify_body(EN_ARTICLE)
    assert kind == "substantive"


def test_link_list_without_numbers_is_unusable_not_substantive() -> None:
    kind, evidence = classify_body(TOC_NO_NUMBERS)
    assert kind == "unusable"
    assert evidence["prose_blocks"] == 0


def test_a_mixed_page_creating_prose_does_not_hide_behind_it() -> None:
    """An index page carrying a stray sentence is still an index page."""
    kind, evidence = classify_body((NAV_SHELL + "\n" + CN_ARTICLE)[:1100])
    assert kind == "navigation"
    assert evidence["reason"] == "link_farm"


def test_tiny_or_empty_body_is_unusable() -> None:
    assert classify_body("Title only")[0] == "unusable"
    assert classify_body("")[0] == "unusable"
    assert classify_body("")[1]["reason"] == "no_body"
