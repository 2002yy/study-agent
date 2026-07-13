"""Versioned GitHub repository snapshots stored through the durable RAG run table."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.domain.runtime_entities import RagRun
from src.repositories.rag_repository import RagRepository


SNAPSHOT_KIND = "github_repo_snapshot"


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class GitHubSnapshotRepository:
    def __init__(self, rag_repository: RagRepository) -> None:
        self.rag_repository = rag_repository

    def create(self, request: dict[str, Any]) -> RagRun:
        return self.rag_repository.create(
            RagRun(kind=SNAPSHOT_KIND, status="running", request=request)
        )

    def complete(self, run_id: str, result: dict[str, Any]) -> RagRun:
        return self.rag_repository.complete(
            run_id,
            result=result,
            index_version=1,
        )

    def fail(self, run_id: str, error: str) -> RagRun:
        return self.rag_repository.fail(run_id, error)

    def get(self, run_id: str) -> RagRun | None:
        run = self.rag_repository.get(run_id)
        if run is None or run.kind != SNAPSHOT_KIND:
            return None
        return run

    def list(self, *, limit: int = 50) -> list[RagRun]:
        return self.rag_repository.list(kind=SNAPSHOT_KIND, limit=limit)

    def find_exact(
        self,
        *,
        repository: str,
        ref: str,
        query: str,
        max_age_seconds: int,
    ) -> RagRun | None:
        for run in self._fresh_completed(max_age_seconds=max_age_seconds):
            request = run.request
            result = run.result
            if str(result.get("repository") or request.get("repository") or "") != repository:
                continue
            requested_ref = str(request.get("ref") or "")
            resolved_ref = str(result.get("ref") or "")
            if ref and ref not in {requested_ref, resolved_ref}:
                continue
            if str(request.get("query") or "") != query:
                continue
            return run
        return None

    def find_latest(
        self,
        *,
        repository: str,
        ref: str,
        max_age_seconds: int,
    ) -> RagRun | None:
        for run in self._fresh_completed(max_age_seconds=max_age_seconds):
            request = run.request
            result = run.result
            if str(result.get("repository") or request.get("repository") or "") != repository:
                continue
            requested_ref = str(request.get("ref") or "")
            resolved_ref = str(result.get("ref") or "")
            if ref and ref not in {requested_ref, resolved_ref}:
                continue
            return run
        return None

    def _fresh_completed(self, *, max_age_seconds: int) -> list[RagRun]:
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=max(0, max_age_seconds)
        )
        result: list[RagRun] = []
        for run in self.list(limit=100):
            if run.status != "completed":
                continue
            updated_at = _timestamp(run.updated_at)
            if updated_at is None or updated_at < cutoff:
                continue
            if not run.result.get("ok"):
                continue
            result.append(run)
        return result
