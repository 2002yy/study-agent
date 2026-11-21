from __future__ import annotations

from pathlib import Path

from src.application.github_snapshot_service import GitHubSnapshotService
from src.application.learning_freshness import LearningFreshnessService
from src.application.learning_outcome_commit import LearningOutcomeCommitService
from src.application.learning_resume import LearningResumeService
from src.application.learning_revalidation import LearningRevalidationService
from src.application.learning_source_evidence import LearningSourceEvidenceService
from src.domain.learning_truth import (
    LearningGoal,
    LearningTopic,
    NextStep,
    UnderstandingClaimResult,
    UnderstandingEvidence,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.github_snapshot_repository import GitHubSnapshotRepository
from src.repositories.learning_truth_repository import LearningTruthRepository
from src.repositories.rag_repository import RagRepository
from src.repositories.runtime_repository import RuntimeRepository

REPOSITORY = "2002yy/study-agent"
REPO_URL = "https://github.com/2002yy/study-agent"
SOURCE_PATH = "src/application/github_source_evidence.py"

COMMIT_A = "a" * 40
TREE_A = "b" * 40
FILE_SHA_A = "source-file-sha-a"

COMMIT_B = "c" * 40
TREE_B = "d" * 40
FILE_SHA_B = "source-file-sha-b"

SYMBOL = "summarize_commit_ci"
QUERY = "summarize commit ci"


def _real_source_text() -> str:
    return (
        Path(__file__).resolve().parents[1] / SOURCE_PATH
    ).read_text(encoding="utf-8")


def _changed_line() -> str:
    return 'requested_sha = str(commit_sha or "").strip().lower()'


def _text_commit_b() -> str:
    return _real_source_text().replace(
        _changed_line(), 'requested_sha = str(commit_sha or "").strip().upper()'
    )


def _primary_for(text: str, *, file_sha: str, commit: str, tree: str) -> dict:
    content = text.splitlines()
    start = next(
        index + 1
        for index, line in enumerate(content)
        if line.startswith("def summarize_commit_ci")
    )
    end = start + 1
    while end <= len(content):
        if content[end - 1].startswith(("def ", "class ", "@", "async ")):
            break
        end += 1
    return {
        "path": SOURCE_PATH,
        "file_sha": file_sha,
        "symbol": SYMBOL,
        "symbol_kind": "function",
        "start_line": start,
        "end_line": end,
        "repository": REPOSITORY,
        "commit_sha": commit,
        "tree_sha": tree,
    }


class PinnedSnapshotter:
    def __init__(self, text: str, *, commit: str, tree: str, file_sha: str) -> None:
        self.text = text
        self.commit = commit
        self.tree = tree
        self.file_sha = file_sha
        self.calls: list[tuple[str, str, str]] = []

    def snapshot(self, repo_url: str, *, query: str = "", ref: str = "") -> dict:
        self.calls.append((repo_url, query, ref))
        return {
            "ok": True,
            "repository": REPOSITORY,
            "ref": ref or "main",
            "requested_ref": ref or "main",
            "commit_sha": self.commit,
            "tree_sha": self.tree,
            "files": [
                {
                    "path": SOURCE_PATH,
                    "sha": self.file_sha,
                    "url": f"{REPO_URL}/blob/{self.commit}/{SOURCE_PATH}",
                    "content": self.text,
                }
            ],
            "file_count": 1,
            "used_chars": len(self.text),
        }


class JourneyHeadResolver:
    def resolve_head(self, repo_url: str, ref: str = "") -> dict:
        return {
            "ok": True,
            "commit_sha": COMMIT_B,
            "tree": {SOURCE_PATH: FILE_SHA_B},
        }


class JourneyBlobReader:
    def __init__(self, blobs: dict[str, str]) -> None:
        self.blobs = blobs
        self.reads: list[str] = []

    def read_blob(self, repo_url: str, sha: str) -> str:
        self.reads.append(sha)
        if sha not in self.blobs:
            raise LookupError(f"missing blob {sha}")
        return self.blobs[sha]


def _snapshot_service(database, snapshotter) -> GitHubSnapshotService:
    return GitHubSnapshotService(
        GitHubSnapshotRepository(RagRepository(database)),
        snapshotter,  # type: ignore[arg-type]
    )


def _converge_with(database, snapshotter):
    return LearningSourceEvidenceService(
        _snapshot_service(database, snapshotter)
    ).search_and_converge(REPO_URL, QUERY, ref="main")


def test_full_golden_journey_source_stale_then_revalidated_rev2(tmp_path):
    """TESTING.md section 7 full journey: steps 1-17 on real source + two commits."""
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    thread = runtime.ensure_chat_thread("golden-journey")
    truth = LearningTruthRepository(database)

    # step 1-2: real source question raises a Topic and a LearningGoal
    topic = truth.create_topic(LearningTopic(title="会话状态与恢复"))
    goal, _context = truth.create_goal_for_thread(
        LearningGoal(
            topic_id=topic.id,
            objective="理解 session recovery 为什么必须保留 ChatTurn identity",
        ),
        thread_id=thread.id,
        focus_pinned=True,
    )

    # step 3-6: commit-pinned retrieval converges to exactly one Primary
    snapshot_a = PinnedSnapshotter(
        _real_source_text(), commit=COMMIT_A, tree=TREE_A, file_sha=FILE_SHA_A
    )
    convergence_a = _converge_with(database, snapshot_a)
    assert convergence_a.claim_ready is True
    assert convergence_a.primary is not None
    assert convergence_a.primary.source.commit_sha == COMMIT_A
    assert convergence_a.primary.source.path == SOURCE_PATH
    assert convergence_a.primary.source.symbol == SYMBOL
    assert convergence_a.one_hop_explored is False
    assert convergence_a.dropped_count == 0

    # step 7: core proposition becomes LearningClaim rev1
    commit_service = LearningOutcomeCommitService(truth)
    first = commit_service.commit(
        topic_id=topic.id,
        goal_id=goal.id,
        claim_text="CI validation is supporting observation, not SourceEvidence identity.",
        claim_kind="invariant",
        convergence=convergence_a,
    )
    assert first.outcome == "claim" and first.claim is not None
    assert first.revision is not None
    rev1_id = first.revision.revision.id
    assert first.revision.revision.reason == "initial"
    assert first.revision.revision.source_commit == COMMIT_A

    # step 9-10: learner explains; pass UnderstandingEvidence is recorded
    evidence = UnderstandingEvidence(
        method="explain",
        prompt="Why is CI identity separate from SourceEvidence identity?",
        user_response="Because a signature lives on the caller path, not the source blob.",
    )
    truth.commit_semantic_closure(
        goal_id=goal.id,
        understanding=evidence,
        results=(
            UnderstandingClaimResult(
                understanding_evidence_id=evidence.id,
                claim_revision_id=rev1_id,
                result="pass",
            ),
        ),
    )

    # step 11: an active school has a Primary NextStep for the remaining gap
    truth.create_next_step(
        NextStep(goal_id=goal.id, text="Inspect the caller/path edge", is_primary=True)
    )
    truth.create_next_step(
        NextStep(goal_id=goal.id, text="Optional: read CI association rules")
    )

    # step 12-13: restart the app; durable resume restores Goal/Claim/NextStep
    restarted_truth = LearningTruthRepository(RuntimeDatabase(database.path))
    resume = LearningResumeService(restarted_truth).build(thread.id)
    assert resume["source"] == "durable"
    assert resume["status"] == "active"
    assert resume["goal"]["objective"] == goal.objective
    assert resume["claims"][0]["text"] == first.revision.revision.claim_text
    assert resume["claims"][0]["understanding_status"] == "confirmed"
    assert resume["claims"][0]["revision_id"] == rev1_id
    assert resume["next_step"]["text"] == "Inspect the caller/path edge"

    # step 14-15: commit B materially changes the Primary body -> stale_candidate,
    # while rev1/confirmed stay readable on the same durable Claim.
    freshness = LearningFreshnessService(
        head_resolver=JourneyHeadResolver(),
        blob_reader=JourneyBlobReader(
            {
                FILE_SHA_A: _real_source_text(),
                FILE_SHA_B: _text_commit_b(),
            }
        ),
    )
    bundle_a = restarted_truth.get_revision(rev1_id)
    assert bundle_a is not None
    stale = freshness.evaluate(bundle_a)
    assert stale.status == "stale_candidate"
    assert stale.head_commit == COMMIT_B
    assert stale.primary["reason"] == "normalized_body_changed"
    assert stale.primary["body_unchanged"] is False
    historical = restarted_truth.get_revision(rev1_id)
    assert historical is not None
    assert historical.revision.reason == "initial"
    assert historical.evidence[0].source.commit_sha == COMMIT_A
    assert restarted_truth.get_claim(first.claim.id) == first.claim

    # step 16-17: explicit revalidation on commit B reuses the same Claim
    # lineage with rev2 instead of a second duplicate Claim.
    snapshot_b = PinnedSnapshotter(
        _text_commit_b(), commit=COMMIT_B, tree=TREE_B, file_sha=FILE_SHA_B
    )
    source_b = LearningSourceEvidenceService(_snapshot_service(database, snapshot_b))
    revalidation = LearningRevalidationService(
        restarted_truth,
        source_evidence_service=source_b,
        commit_service=LearningOutcomeCommitService(restarted_truth),
        freshness_service=freshness,
    )
    result = revalidation.revalidate(thread.id, first.claim.id)
    assert result.outcome == "revalidated"
    assert result.claim_id == first.claim.id
    assert result.revision_id != rev1_id
    assert result.head_commit == COMMIT_B
    assert result.freshness_status == "current"
    assert snapshot_b.calls and snapshot_b.calls[0][1] == first.revision.revision.claim_text

    bundles = restarted_truth.list_revisions(first.claim.id)
    assert [bundle.revision.id for bundle in bundles] == [rev1_id, result.revision_id]
    assert [bundle.revision.reason for bundle in bundles] == ["initial", "revalidated"]
    assert bundles[-1].revision.source_commit == COMMIT_B
    assert bundles[-1].evidence[0].source.commit_sha == COMMIT_B
    assert bundles[-1].evidence[0].source.file_sha == FILE_SHA_B
    assert restarted_truth.list_claims(topic.id) == [first.claim]

    # after revalidation the projection is current again, same lineage
    completed = freshness.evaluate(bundles[-1])
    assert completed.status == "current"
    assert completed.primary["reason"] == "identical_blob_sha"
    after = LearningResumeService(restarted_truth).build(thread.id)
    assert after["claims"][0]["revision_id"] == result.revision_id
    assert after["claims"][0]["understanding_status"] == "confirmed"
    assert after["claims"][0]["primary_evidence"]["commit_sha"] == COMMIT_B
    assert after["claims"][0]["primary_evidence"]["file_sha"] == FILE_SHA_B
    assert len(after["claims"]) == 1