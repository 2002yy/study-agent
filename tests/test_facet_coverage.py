from __future__ import annotations

from src.web.research.facet_coverage import (
    assess_coverage,
    community_hosts_for,
    next_gap_step,
    plan_facets,
)

QUESTION = "SQLite WAL 在四个 worker、后台索引和长事务下有什么限制？并发写入、网络文件系统、备份恢复"
PLAN = [
    {"rq_id": "rq-writes", "query": "SQLite WAL concurrent write locking"},
    {"rq_id": "rq-long", "query": "SQLite long transaction checkpoint"},
    {"rq_id": "rq-nfs", "query": "SQLite WAL network filesystem"},
    {"rq_id": "rq-backup", "query": "SQLite WAL backup restore"},
]
QUESTIONS = {
    "rq-writes": "并发写入有什么限制",
    "rq-long": "长事务与检查点的影响",
    "rq-nfs": "网络文件系统下是否可用",
    "rq-backup": "备份与恢复要怎么做",
}
WAL = (
    "https://sqlite.org/wal.html",
    "WAL mode: concurrent writes are serialized; a long transaction prevents "
    "checkpointing; network filesystems are unsafe for WAL.",
)


def facets():
    return plan_facets(PLAN, QUESTION, questions=QUESTIONS)


def test_terms_shared_by_every_question_are_not_facet_distinctive():
    by_id = {facet.id: facet for facet in facets()}

    # SQLite/WAL identify the subject, not one facet, so they must not let a
    # WAL page look like it answers the backup question.
    assert all("sqlite" not in facet.distinctive for facet in by_id.values())
    assert "backup" in by_id["rq-backup"].distinctive
    assert "备份" in by_id["rq-backup"].distinctive


def test_a_body_that_addresses_three_constraints_leaves_the_fourth_open():
    report = assess_coverage(
        facets(), [WAL], question=QUESTION, official_hosts=("sqlite.org",)
    )

    assert report.complete is False
    assert [item.facet_id for item in report.uncovered] == ["rq-backup"]
    assert report.missing_official is False  # sqlite.org itself was read
    step = next_gap_step(
        report,
        facets=facets(),
        question=QUESTION,
        official_hosts=("sqlite.org",),
        searched=[row["query"] for row in PLAN],
    )
    assert step is not None
    assert step.reason == "uncovered_facet"
    assert step.facet_id == "rq-backup"


def test_every_constraint_covered_by_a_read_body_is_complete():
    body = WAL[1] + " Use the backup API to restore a copy."
    report = assess_coverage(
        facets(), [(WAL[0], body)], question=QUESTION, official_hosts=("sqlite.org",)
    )

    assert report.complete is True
    assert report.uncovered == ()
    assert next_gap_step(
        report, facets=facets(), question=QUESTION, official_hosts=("sqlite.org",)
    ) is None


def test_chinese_facets_are_not_judged_against_an_english_only_corpus():
    report = assess_coverage(
        facets(), [WAL], question=QUESTION, official_hosts=("sqlite.org",)
    )

    # The English page cannot be checked against a Chinese question, but its
    # ASCII planned query can: that half is assessed, and it is covered.
    covered = {item.facet_id for item in report.facets if item.covered}
    assert {"rq-writes", "rq-long", "rq-nfs"} <= covered


def test_a_question_whose_facets_share_no_vocabulary_is_never_complete():
    plan = [{"rq_id": "rq-a", "query": "alpha topic"}, {"rq_id": "rq-b", "query": "beta topic"}]
    report = assess_coverage(
        plan_facets(plan, "两个不同的问题"),
        [("https://example.org/x", "完全不相关的正文内容")],
        question="两个不同的问题",
    )

    # No facet can be verified from this body, so coverage never claims it is
    # sufficient and no phantom gap search is invented.
    assert report.complete is False
    assert all(not item.assessable or not item.covered for item in report.facets)


def test_one_community_thread_satisfies_the_source_expectation():
    question = "Notion 和 Obsidian 哪个更适合长期笔记？求真实使用体验"
    hosts = community_hosts_for(question)
    assert hosts == ("v2ex.com", "linux.do")
    plan = [
        {"rq_id": "rq-1", "query": "Notion Obsidian long term notes"},
        {"rq_id": "rq-2", "query": "Notion Obsidian real user experience"},
    ]
    vendor = ("https://www.notion.so/product", "Notion long term notes, real user experience.")
    report = assess_coverage(plan_facets(plan, question), [vendor], question=question,
                             community_hosts=hosts)

    step = next_gap_step(report, facets=plan_facets(plan, question), question=question,
                         searched=[row["query"] for row in plan])
    assert step is not None
    assert step.reason == "missing_community_source"
    assert "site:v2ex.com" in step.query
    assert "长期笔记" in step.query

    thread = ("https://www.v2ex.com/t/123456", "长期笔记的 real user experience")
    satisfied = assess_coverage(plan_facets(plan, question), [vendor, thread],
                                question=question, community_hosts=hosts)
    assert satisfied.missing_community_hosts == ()


def test_domain_communities_are_prioritized_without_routing_to_video_only_pages():
    assert community_hosts_for("星铁虚构叙事配队推荐")[0] == "miyoushe.com"
    assert community_hosts_for("校招牛客面经真实体验")[0] == "nowcoder.com"
    assert community_hosts_for("RTX 显卡装机真实体验")[0] == "chiphell.com"
    assert community_hosts_for("Notion vs Obsidian long term notes recommendation")[0] == "reddit.com"


def test_an_official_gap_never_scopes_a_chinese_only_phrase():
    question = "劳动合同 试用期 最长 规定"
    plan = [
        {"rq_id": "rq-1", "query": "劳动合同 试用期 规定"},
        {"rq_id": "rq-2", "query": "试用期 最长 期限"},
    ]
    report = assess_coverage(
        plan_facets(plan, question),
        [("https://example.com/a", "试用期规定的内容")],
        question=question,
        official_hosts=("gov.cn",),
    )

    assert report.missing_official is True
    step = next_gap_step(report, facets=plan_facets(plan, question), question=question,
                         official_hosts=("gov.cn",))
    assert step is not None
    # site:gov.cn + a Chinese sentence returns dictionary pages, so the gap is
    # expressed as a facet question instead of a fabricated scoped query.
    assert "site:gov.cn" not in step.query


def test_scattered_words_in_a_generic_tutorial_do_not_cover_a_phrase_facet():
    question = "SQLite 的备份恢复和网络文件系统要注意什么"
    plan = [
        {"rq_id": "rq-nfs", "query": "SQLite WAL network filesystem"},
        {"rq_id": "rq-backup", "query": "SQLite WAL backup restore"},
    ]
    questions = {"rq-nfs": "网络文件系统能不能用", "rq-backup": "备份恢复要注意什么"}
    tutorial = (
        "https://www.runoob.com/sqlite/sqlite-tutorial.html",
        "SQLite 教程：文件系统与操作系统的关系，数据库的备份方式，网络配置说明。",
    )
    report = assess_coverage(plan_facets(plan, question, questions=questions),
                             [tutorial], question=question)

    status = {item.facet_id: item for item in report.facets}
    # "文件系统" alone is not "网络文件系统"; only the phrase it names counts.
    assert status["rq-nfs"].covered is False
    assert status["rq-backup"].covered is False

    real = (
        "https://sqlite.org/wal.html",
        "WAL is unsafe on a network filesystem. Use the backup API to restore.",
    )
    covered = assess_coverage(plan_facets(plan, question, questions=questions),
                              [real], question=question)
    assert {item.facet_id for item in covered.facets if item.covered} == {
        "rq-nfs", "rq-backup"
    }


def test_a_query_already_searched_is_never_repeated():
    report = assess_coverage(facets(), [WAL], question=QUESTION,
                             official_hosts=("sqlite.org",))
    searched = [row["query"] for row in PLAN] + [QUESTIONS["rq-backup"]]

    step = next_gap_step(report, facets=facets(), question=QUESTION,
                         official_hosts=("sqlite.org",), searched=searched)
    assert step is None
