"""Deterministic regressions for window qualification (M4-C5 window-selection close-out).

These pin the SOURCE-LEVEL behaviours the review asked for, without a product glossary and
without any network or model call:
  * a page whose dominant subject is another product contributes no window;
  * a bare mention with a copula is not candidate-relevant;
  * a long page keeps its later mechanism text even at the production per-goal limit;
  * a verified quote inside a body is covered by the selected windows.
"""

from __future__ import annotations

from src.web.research_claims import MAX_WINDOWS_PER_GOAL, evidence_windows


class Body:
    def __init__(self, text: str, url: str = "") -> None:
        self.text = text
        self.url = url
        self.quality = {"prose_chars": len(text)}


def _windows(text: str, terms, sides=()):
    return evidence_windows(tuple(terms), {"S1": Body(text, "https://h.example/x")},
                             limit=MAX_WINDOWS_PER_GOAL, sides=tuple(sides))


FOREIGN_PRIMARY = (
    "MySQL 使用 undo log 实现 MVCC。InnoDB 通过 read view 决定版本可见性，因此回滚很快。"
    "MySQL 的版本链由 undo log 维护，所以 InnoDB 的并发性能很好，rollback segment 也很重要。"
    "MySQL 的 MVCC 被广泛使用，mysql 的文档介绍了 innodb 的实现，mysql 用户很熟悉。"
    "PostgreSQL 也支持 MVCC。"
)

COPULA_ONLY = (
    "MVCC 是一个概念，它非常重要。MVCC 是一个名词，也是一个缩写。"
    "MVCC 是被广泛讨论的话题，它是数据库领域的内容。"
)

LONG_PAGE_HEAD = "漏斗是 Minecraft 中的一种方块，它属于红石元件。" * 60
LONG_PAGE_TAIL = (
    "漏斗会从上方吸收物品实体，因此可以把物品送到它朝向的容器中。"
    "漏斗的冷却时间在 Java 版中为 7 游戏刻，因为红石信号会影响它的行为。"
)


def test_a_foreign_subject_page_contributes_nothing():
    """Mentioning the subject once does not earn extraction rights on another product's page."""
    assert _windows(FOREIGN_PRIMARY, ("PostgreSQL", "MVCC", "读写", "阻塞")) == []


def test_a_bare_mention_with_a_copula_is_not_relevant():
    assert _windows(COPULA_ONLY, ("MVCC", "PostgreSQL")) == []


def test_later_mechanism_text_survives_the_per_goal_limit():
    text = LONG_PAGE_HEAD + LONG_PAGE_TAIL
    windows = _windows(text, ("漏斗", "投掷器"), sides=("漏斗", "投掷器"))
    assert windows, "material in the latter half must still be offered"
    assert max(int(w["span_start"]) for w in windows) > len(text) // 2


def test_a_verified_quote_is_covered_by_the_selected_windows():
    text = LONG_PAGE_HEAD + "漏斗不会在开启时吸取物品，因为它的物品槽可能已被占满。" + LONG_PAGE_TAIL
    quote = "漏斗不会在开启时吸取物品，因为它的物品槽可能已被占满。"
    windows = _windows(text, ("漏斗",), sides=("漏斗",))
    assert windows
    assert any(quote in str(w.get("excerpt") or "") for w in windows)
