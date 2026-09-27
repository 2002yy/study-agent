"""§150 explicit research-memory publication and historical-lead recall."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import json

import pytest

import src.infrastructure.sqlite.database as sqlite_database
from src.application.research_memory_service import ResearchMemoryService
from src.domain.evidence import ClaimEvidenceLinkV1
from src.domain.runtime_entities import WebLookupRun
from src.infrastructure.sqlite.database import RuntimeDatabase, schema_version
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import (
    EvidenceCluster,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchEvidence,
    ResearchQuestion,
    build_research_state,
)
from src.web.research.evidence_units import EvidenceUnit, RequiredUnit
from src.web.research.persistent_memory import (
    ResearchMemoryRevision,
    known_research_evidence_ids,
)


def _thread(database: RuntimeDatabase, thread_id: str) -> None:
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO chat_threads(id, status, created_at, updated_at)
               VALUES (?, 'active', '2026-09-27T00:00:00+00:00',
                       '2026-09-27T00:00:00+00:00')""",
            (thread_id,),
        )


def _run(thread_id: str, *, status: str = "completed", mode: str = "active") -> WebLookupRun:
    selected = [{
        "item": {"url": "https://example.org/primary", "title": "Primary", "published_at": "2026-09-25"},
        "assessment": {"url": "https://example.org/primary", "source_id": "source-1"},
        "read_status": "read",
    }]
    draft = WebLookupRun(
        owner_thread_id=thread_id, status=status, selected_sources=selected,
        provider_status="ok", query="Is feature X supported?",
        completed_at="2026-09-27T00:00:00+00:00",
    )
    evidence_id = known_research_evidence_ids(draft)[0]
    state = build_research_state(
        mode=mode,
        questions=[ResearchQuestion("q1", draft.query, "critical")],
        claims=[ResearchClaim(
            "c1", "q1", "Feature X is supported.", "factual", "critical", "searching",
            EvidenceRequirement(
                source_roles=("primary",), required_units=(RequiredUnit("u1"),),
                max_age_days=7,
            ),
        )],
        evidence=[ResearchEvidence(
            evidence_id, locator="https://example.org/primary",
            lifecycle_status="read", extraction_status="eligible",
            published_at="2026-09-25",
            units=(EvidenceUnit(
                "u1", source="https://example.org/primary", content="example",
                supports=("c1",), provenance="read:primary",
            ),),
        )],
        evidence_links=[ResearchClaimEvidenceLink(
            ClaimEvidenceLinkV1("c1", evidence_id, "supports", 0.9),
            source_role="primary", source_cluster_id="k1",
            locator="https://example.org/primary",
        )],
        source_clusters=[EvidenceCluster("k1", (evidence_id,), "primary")],
        gaps=[], conflict_gaps=[],
        budget=ResearchBudget(20, 8, 45, 60),
        known_evidence_ids=(evidence_id,),
        reference_date="2026-09-27",
    )
    return replace(draft, research_context={"claim_engine": state.to_dict()})


@pytest.fixture
def memory(tmp_path):
    database = RuntimeDatabase(tmp_path / "memory.sqlite")
    service = ResearchMemoryService(database)
    _thread(database, "thread-1")
    _thread(database, "thread-2")
    return database, service


def test_migration_and_explicit_terminal_publication(memory):
    database, service = memory
    with database.connect() as connection:
        assert schema_version(connection) == 24
    run = WebLookupRepository(database).create(_run("thread-1"))
    assert service.recall("thread-1", run.query, today=date(2026, 9, 27)) == ()

    revision = service.publish(run.id, expected_cursor_version=0)
    assert service.memory.cursor_version("thread-1") == 1
    assert revision.claims[0].status == "unresolved"
    assert revision.claims[0].semantic_adequacy == "adequate"
    assert revision.claims[0].audited_conclusion == ""
    assert revision.claims[0].support_refs == (revision.evidence_refs[0].evidence_id,)
    assert revision.evidence_refs[0].evidence_id.startswith(f"{run.id}:")
    assert service.publish(run.id, expected_cursor_version=0) == revision
    assert service.memory.cursor_version("thread-1") == 1
    candidate, = service.recall("thread-1", run.query, today=date(2026, 9, 27))
    assert (candidate.status, candidate.relevance, candidate.freshness) == (
        "available", "same_topic", "current",
    )
    assert service.recall("thread-2", run.query, today=date(2026, 9, 27)) == ()
    assert service.recall("thread-1", "different", today=date(2026, 10, 10))[0].freshness == "stale"
    assert candidate.revision is not None
    assert not hasattr(candidate.revision, "evidence")


def test_rejects_unqualified_source_and_corrupt_state(memory):
    database, service = memory
    repository = WebLookupRepository(database)
    running = repository.create(_run("thread-1", status="running"))
    shadow = repository.create(_run("thread-1", mode="shadow"))
    with pytest.raises(ValueError, match="terminal"):
        service.publish(running.id, expected_cursor_version=0)
    with pytest.raises(ValueError, match="validated active"):
        service.publish(shadow.id, expected_cursor_version=0)
    bad = _run("thread-1")
    bad.research_context["claim_engine"]["evidence"][0]["evidence_id"] = "forged"
    bad = repository.create(bad)
    with pytest.raises(ValueError, match="validated active"):
        service.publish(bad.id, expected_cursor_version=0)


def test_cursor_digest_and_transaction_rollback(memory):
    database, service = memory
    repository = WebLookupRepository(database)
    first = repository.create(_run("thread-1"))
    second = repository.create(_run("thread-1"))
    revision = service.publish(first.id, expected_cursor_version=0)
    with pytest.raises(ValueError, match="cursor conflict"):
        service.publish(second.id, expected_cursor_version=0)
    assert service.memory.cursor_version("thread-1") == 1
    with database.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM research_memory_revisions").fetchone()[0]
    assert count == 1
    with pytest.raises(ValueError, match="digest conflict"):
        service.memory.publish(
            replace(revision, state_digest="0" * 64), expected_cursor_version=1,
        )
    with pytest.raises(ValueError, match="prior revision owner mismatch"):
        service.publish(second.id, expected_cursor_version=1, prior_revision_ids=("missing",))
    assert service.memory.cursor_version("thread-1") == 1
    assert service.memory.recall("thread-1", first.query, today=date(2026, 9, 27))[0].revision_id == revision.revision_id


def test_strict_parser_and_bounded_corrupt_recall(memory):
    database, service = memory
    run = WebLookupRepository(database).create(_run("thread-1"))
    revision = service.publish(run.id, expected_cursor_version=0)
    payload = revision.to_dict()
    payload["schema_version"] = "research-memory-v2"
    with pytest.raises(ValueError, match="unsupported"):
        ResearchMemoryRevision.from_dict(payload)
    payload = revision.to_dict()
    payload["claims"][0]["status"] = "confirmed"
    with pytest.raises(ValueError, match="qualified audit"):
        ResearchMemoryRevision.from_dict(payload)
    payload = revision.to_dict()
    payload["evidence_refs"][0]["evidence_id"] = "other:ref"
    with pytest.raises(ValueError, match="namespace"):
        ResearchMemoryRevision.from_dict(payload)
    payload = revision.to_dict()
    payload["audit_verdict"] = "pass"
    payload["audit_judge"] = "caller-supplied"
    with pytest.raises(ValueError, match="not qualified"):
        ResearchMemoryRevision.from_dict(payload)
    payload = revision.to_dict()
    payload["claims"][0]["covered_units"] = []
    with pytest.raises(ValueError, match="coverage mismatch"):
        ResearchMemoryRevision.from_dict(payload)
    with database.connect() as connection:
        connection.execute(
            "UPDATE research_memory_revisions SET payload = ? WHERE revision_id = ?",
            (json.dumps({"schema_version": "research-memory-v1"}), revision.revision_id),
        )
    candidate, = service.recall("thread-1", run.query, today=date(2026, 9, 27))
    assert (candidate.status, candidate.reason, candidate.revision) == (
        "unavailable", "invalid_memory_revision", None,
    )


def test_failure_before_commit_leaves_no_revision_or_cursor(memory):
    database, service = memory
    run = WebLookupRepository(database).create(_run("thread-1"))
    with database.connect() as connection:
        connection.execute("""
            CREATE TRIGGER reject_memory_insert BEFORE INSERT ON research_memory_revisions
            BEGIN SELECT RAISE(ABORT, 'injected crash'); END
        """)
    with pytest.raises(Exception, match="injected crash"):
        service.publish(run.id, expected_cursor_version=0)
    assert service.memory.cursor_version("thread-1") == 0
    assert service.recall("thread-1", run.query, today=date(2026, 9, 27)) == ()
    with database.connect() as connection:
        connection.execute("DROP TRIGGER reject_memory_insert")
    revision = service.publish(run.id, expected_cursor_version=0)
    assert service.publish(run.id, expected_cursor_version=0) == revision


def test_source_version_and_owner_are_rechecked_at_commit_and_recall(memory):
    database, service = memory
    run = WebLookupRepository(database).create(_run("thread-1"))
    revision = service.publish(run.id, expected_cursor_version=0)
    with pytest.raises(ValueError, match="owner mismatch"):
        service.memory.publish(
            replace(revision, owner_thread_id="thread-2"), expected_cursor_version=0,
        )
    with database.connect() as connection:
        connection.execute("UPDATE web_lookup_runs SET version = version + 1 WHERE id = ?", (run.id,))
    candidate, = service.recall("thread-1", run.query, today=date(2026, 9, 27))
    assert (candidate.status, candidate.reason) == ("unavailable", "memory_source_unavailable")


def test_undated_and_conflicted_history_never_implies_current(memory):
    database, service = memory
    run = WebLookupRepository(database).create(_run("thread-1"))
    revision = service.publish(run.id, expected_cursor_version=0)
    payload = revision.to_dict()
    payload["evidence_refs"][0]["published_at"] = ""
    payload["claims"][0]["conflict_status"] = "unresolved_conflict"
    with database.connect() as connection:
        connection.execute(
            "UPDATE research_memory_revisions SET payload = ? WHERE revision_id = ?",
            (json.dumps(payload), revision.revision_id),
        )
    candidate, = service.recall("thread-1", run.query, today=date(2026, 9, 27))
    assert candidate.freshness == "unknown"
    assert candidate.revision is not None
    assert candidate.revision.claims[0].conflict_status == "unresolved_conflict"
    assert candidate.reason == "historical_lead_only"


def test_v23_upgrade_preserves_existing_runs(tmp_path, monkeypatch):
    database = RuntimeDatabase(tmp_path / "upgrade.sqlite")
    with monkeypatch.context() as patch:
        patch.setattr(sqlite_database, "SCHEMA_VERSION", 23)
        patch.setattr(
            sqlite_database, "MIGRATIONS",
            tuple(item for item in sqlite_database.MIGRATIONS if item[0] <= 23),
        )
        database.initialize()
        old = WebLookupRepository(database).create(WebLookupRun(query="legacy run"))
        with database.connect() as connection:
            assert schema_version(connection) == 23
    database.initialize()
    with database.connect() as connection:
        assert schema_version(connection) == 24
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'research_memory_revisions'"
        ).fetchone()[0] == 1
    assert WebLookupRepository(database).get(old.id).query == "legacy run"
