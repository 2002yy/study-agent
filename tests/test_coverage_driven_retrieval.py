from __future__ import annotations

import json
import time
from typing import Any

from src.web.research_recovery import recover_public_research, recovery_summary
from src.web.semantic_recovery import ResearchEpisode, ResearchSemanticSession
from src.web.tool_evidence import evidence_tool_calls

ORIGINAL = "SQLite WAL concurrent writes and backup limits"
PLAN = [
    {"rq_id": "rq-writes", "query": "SQLite WAL concurrent write limits"},
    {"rq_id": "rq-backup", "query": "SQLite WAL backup restore"},
]
QUESTIONS = {
    "rq-writes": "concurrent write limits",
    "rq-backup": "backup and restore procedure",
}
WAL_BODY = (
    "In WAL mode readers proceed while a write transaction is active. "
    "Use the backup API to restore a copy."
)
INDEX_BODY = "SQLite documentation index: lists every page on the site."
WRITES_BODY = "Concurrent writers wait for the single write lock; limits apply per database."


def row(url: str, title: str = "") -> dict[str, str]:
    return {"title": title or url.rsplit("/", 1)[-1], "url": url, "snippet": "candidate"}


class ScriptedGateway:
    """Search answers keyed by the exact query the recovery loop sends."""

    def __init__(self, answers: dict[str, list[dict[str, str]]], bodies: dict[str, Any]):
        self.answers = answers
        self.bodies = bodies
        self.queries: list[str] = []
        self.reads: list[str] = []

    def search_exact(self, query: str, *, max_results: int) -> dict[str, Any]:
        self.queries.append(query)
        rows = self.answers.get(query, [])
        if isinstance(rows, Exception):
            raise rows
        return {"status": "ok" if rows else "empty", "results": rows}

    def read(self, url: str, *, max_chars: int, timeout: float) -> dict[str, Any]:
        self.reads.append(url)
        body = self.bodies.get(url, "")
        if isinstance(body, Exception):
            raise body
        return {"ok": True, "url": url, "content": body}


def session_for(questions: dict[str, str]) -> ResearchSemanticSession:
    """A real session whose model calls are deterministic fixtures."""

    def completion(*, messages, timeout, task_name):
        data = json.loads(messages[-1]["content"])
        ids = [str(item["id"]) for item in data["items"]]
        first = str(data["questions"][0]["id"])
        return json.dumps(
            {
                "task_id": data["task_id"],
                "decisions": [
                    {"id": item, "related": True, "rq_ids": [first], "reason": "fixture"}
                    for item in ids
                ],
            },
            ensure_ascii=False,
        )

    session = ResearchSemanticSession(
        completion, deadline=time.monotonic() + 30, should_cancel=lambda: False
    )
    session.episode = ResearchEpisode(
        task_id="task-1",
        thread_id="thread-1",
        original_question=ORIGINAL,
        questions=[{"id": key, "question": value} for key, value in questions.items()],
    )
    return session


def run(gateway: ScriptedGateway, *, session: bool = True, plan=PLAN, questions=QUESTIONS):
    return recover_public_research(
        gateway,
        ORIGINAL,
        query_plan=plan,
        semantic_session=session_for(questions) if session else None,
    )


def test_a_covered_planned_question_does_not_get_its_own_search_again():
    gateway = ScriptedGateway(
        {
            "SQLite WAL concurrent write limits": [row("https://sqlite.org/wal.html")],
            "site:sqlite.org Sqlite WAL concurrent": [row("https://sqlite.org/docs.html")],
            "concurrent write limits": [row("https://sqlite.org/wal.html")],
        },
        {
            "https://sqlite.org/wal.html": WAL_BODY,
            "https://sqlite.org/docs.html": INDEX_BODY,
        },
    )

    calls = run(gateway)
    summary = recovery_summary(calls)

    # The third planned question (backup) was already answered by the first
    # page, so its slot went to the question that was still missing.
    assert gateway.queries[2] == "concurrent write limits"
    assert [step["reason"] for step in summary["gap_steps"]] == ["uncovered_facet"]
    assert summary["gap_steps"][0]["facet_id"] == "rq-writes"


def test_an_uncovered_planned_question_gets_the_spare_search_slot():
    gateway = ScriptedGateway(
        {
            "SQLite WAL concurrent write limits": [row("https://sqlite.org/wal.html")],
            "site:sqlite.org Sqlite WAL concurrent": [row("https://sqlite.org/docs.html")],
            "SQLite WAL backup restore": [row("https://sqlite.org/wal.html")],
            "backup and restore procedure": [row("https://sqlite.org/backup.html")],
        },
        {
            "https://sqlite.org/wal.html": WRITES_BODY,
            "https://sqlite.org/docs.html": INDEX_BODY,
            "https://sqlite.org/backup.html": "Backup and restore procedure for a live database.",
        },
    )

    calls = run(gateway)
    summary = recovery_summary(calls)

    assert len(gateway.queries) == 4
    assert gateway.queries[3] == "backup and restore procedure"
    assert summary["gap_steps"][-1]["reason"] == "uncovered_facet"
    assert summary["gap_steps"][-1]["facet_id"] == "rq-backup"
    # The gap search found the missing page, so the report now shows the once
    # uncovered question as covered by the body it found.
    assert summary["facet_coverage"]["missing_official_source"] is False
    assert "https://sqlite.org/backup.html" in gateway.reads
    assert evidence_tool_calls(calls)


def test_coverage_satisfied_stops_before_the_remaining_searches(monkeypatch):
    monkeypatch.setenv("WEB_RESEARCH_COVERAGE_STOP", "on")
    gateway = ScriptedGateway(
        {"SQLite WAL concurrent write limits": [row("https://sqlite.org/wal.html")]},
        {"https://sqlite.org/wal.html": WAL_BODY.replace("restore a copy", "restore a copy; concurrent write limits apply")},
    )

    calls = run(gateway)
    summary = recovery_summary(calls)

    assert len(gateway.queries) == 1
    assert summary["coverage_stop"] is True
    assert summary["facet_coverage"]["complete"] is True


def test_early_completion_is_opt_in(monkeypatch):
    """Without the switch the run keeps its old, bounded phase count."""

    monkeypatch.delenv("WEB_RESEARCH_COVERAGE_STOP", raising=False)
    gateway = ScriptedGateway(
        {"SQLite WAL concurrent write limits": [row("https://sqlite.org/wal.html")]},
        {"https://sqlite.org/wal.html": WAL_BODY.replace("restore a copy", "restore a copy; concurrent write limits apply")},
    )

    calls = run(gateway)
    summary = recovery_summary(calls)

    assert len(gateway.queries) > 1
    assert summary["coverage_stop"] is False
    assert summary["facet_coverage"]["complete"] is True


def test_a_missing_community_thread_is_searched_before_the_facet():
    question = "Notion vs Obsidian long term notes recommendation"
    plan = [
        {"rq_id": "rq-notes", "query": "Notion Obsidian long term notes"},
        {"rq_id": "rq-experience", "query": "Notion Obsidian real user experience"},
    ]
    questions = {"rq-notes": "long term notes", "rq-experience": "real user experience"}
    gateway = ScriptedGateway(
        {
            "Notion Obsidian long term notes": [row("https://www.notion.so/product")],
            "site:notion.so Notion": [row("https://www.notion.so/product")],
            "notion obsidian real user experience site:reddit.com": [
                row("https://www.reddit.com/r/Notion/comments/x/y")
            ],
        },
        {
            "https://www.notion.so/product": "Notion long term notes; real user experience compared.",
            "https://www.reddit.com/r/Notion/comments/x/y": "Real user experience comparison.",
        },
    )

    calls = recover_public_research(
        gateway,
        question,
        query_plan=plan,
        semantic_session=session_for(questions),
    )
    summary = recovery_summary(calls)

    assert summary["gap_steps"][0]["reason"] == "missing_community_source"
    assert summary["gap_steps"][0]["host"] == "reddit.com"
    assert any("site:reddit.com" in query for query in gateway.queries)


def test_an_irrelevant_homepage_does_not_count_as_facet_coverage():
    gateway = ScriptedGateway(
        {
            "SQLite WAL concurrent write limits": [row("https://example.org/")],
            "site:sqlite.org Sqlite WAL concurrent": [row("https://sqlite.org/docs.html")],
            "backup and restore procedure": [row("https://sqlite.org/backup.html")],
        },
        {
            "https://example.org/": "Welcome to our video app. Home blog pricing.",
            "https://sqlite.org/docs.html": INDEX_BODY,
            "https://sqlite.org/backup.html": "Backup and restore procedure for a live database.",
        },
    )

    calls = run(gateway)
    summary = recovery_summary(calls)

    uncovered = summary["facet_coverage"]["uncovered_facets"]
    assert "rq-writes" in uncovered
    assert "https://example.org/" not in [
        call["arguments"]["url"] for call in evidence_tool_calls(calls)
    ]
    assert summary["gap_steps"][-1]["facet_id"] in {"rq-writes", "rq-backup"}


def test_a_search_outage_on_the_first_step_still_produces_a_gap_plan():
    gateway = ScriptedGateway(
        {
            "SQLite WAL concurrent write limits": TimeoutError("provider_outage"),
            "site:sqlite.org Sqlite WAL concurrent": [row("https://sqlite.org/wal.html")],
        },
        {"https://sqlite.org/wal.html": WRITES_BODY},
    )

    calls = run(gateway)
    summary = recovery_summary(calls)

    assert summary["provider_failures"] >= 1
    assert summary["facet_coverage"] is not None
    assert summary["facet_coverage"]["uncovered_facets"]
    assert summary["gap_steps"]


def test_an_identical_planned_query_is_not_searched_twice():
    plan = [
        {"rq_id": "rq-a", "query": "SQLite WAL concurrent write limits"},
        {"rq_id": "rq-b", "query": "SQLite WAL concurrent write limits"},
    ]
    gateway = ScriptedGateway(
        {
            "SQLite WAL concurrent write limits": [row("https://sqlite.org/wal.html")],
            "site:sqlite.org Sqlite WAL concurrent": [row("https://sqlite.org/docs.html")],
        },
        {
            "https://sqlite.org/wal.html": WRITES_BODY,
            "https://sqlite.org/docs.html": INDEX_BODY,
        },
    )

    calls = recover_public_research(
        gateway,
        ORIGINAL,
        query_plan=plan,
        semantic_session=session_for({"rq-a": "concurrent write limits",
                                      "rq-b": "concurrent write limits"}),
    )
    summary = recovery_summary(calls)

    assert gateway.queries.count("SQLite WAL concurrent write limits") == 1
    assert summary["duplicate_queries_skipped"] == 1


def test_a_failing_gap_search_keeps_the_earlier_evidence():
    gateway = ScriptedGateway(
        {
            "SQLite WAL concurrent write limits": [row("https://sqlite.org/wal.html")],
            "site:sqlite.org Sqlite WAL concurrent": [row("https://sqlite.org/docs.html")],
            "SQLite WAL backup restore": TimeoutError("provider_timeout"),
        },
        {
            "https://sqlite.org/wal.html": WRITES_BODY,
            "https://sqlite.org/docs.html": INDEX_BODY,
        },
    )

    calls = run(gateway)
    summary = recovery_summary(calls)

    assert summary["provider_failures"] >= 1
    assert summary["facet_coverage"]["uncovered_facets"] == ["rq-backup"]
    urls = [call["arguments"]["url"] for call in evidence_tool_calls(calls)]
    assert "https://sqlite.org/wal.html" in urls
