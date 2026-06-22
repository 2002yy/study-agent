"""Server-owned NewsRun application workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.application.group_chat_service import GroupChatService
from src.domain.runtime_entities import NewsRun, new_id
from src.repositories.news_repository import NewsRepository


def _search(query: str, *, max_items: int):
    from src import api

    return api.run_search_stage(query, max_items=max_items)


def _enrich(items, **kwargs):
    from src import api

    return api.run_enrich_stage(items, **kwargs)


def _digest(items, **kwargs):
    from src import api

    return api.run_digest_stage(items, **kwargs)


def _discuss(digest: str, **kwargs):
    from src import api

    return api.run_discussion_stage(digest, **kwargs)


def _runtime_modes():
    from src import api

    return api.load_runtime_modes()


@dataclass(frozen=True)
class NewsDependencies:
    search: Callable[..., Any] = _search
    enrich: Callable[..., Any] = _enrich
    digest: Callable[..., Any] = _digest
    discuss: Callable[..., Any] = _discuss
    load_runtime_modes: Callable[..., Any] = _runtime_modes


class NewsService:
    def __init__(
        self,
        repository: NewsRepository,
        group_service: GroupChatService,
        dependencies: NewsDependencies | None = None,
    ):
        self.repository = repository
        self.group_service = group_service
        self.dependencies = dependencies or NewsDependencies()

    def create(self, query: str) -> NewsRun:
        return self.repository.create(NewsRun(query=query.strip(), stage="created"))

    def search(self, run_id: str, *, max_items: int) -> NewsRun:
        operation_id = new_id("news_search")
        run = self.repository.acquire_operation(
            run_id, operation_id, expected_stages=("created",)
        )
        try:
            items = self.dependencies.search(run.query, max_items=max_items)
            return self.repository.complete_operation(
                run.id,
                operation_id,
                stage="searched",
                items=items,
            )
        except Exception as exc:
            self.repository.fail_operation(run.id, operation_id, str(exc))
            raise

    def enrich(
        self,
        run_id: str,
        *,
        max_articles: int,
        max_chars_per_article: int,
        safe_mode: bool | None,
    ) -> NewsRun:
        operation_id = new_id("news_enrich")
        run = self.repository.acquire_operation(
            run_id, operation_id, expected_stages=("searched",)
        )
        try:
            profile = self.dependencies.load_runtime_modes().profile
            safe = profile.safe_mode if safe_mode is None else safe_mode
            if safe or max_articles == 0 or not profile.allow_article_network_read:
                reason = (
                    "safe_mode"
                    if safe
                    else "read_articles_disabled"
                    if max_articles == 0
                    else profile.article_network_read_reason
                )
                return self.repository.complete_operation(
                    run.id,
                    operation_id,
                    stage="enrich_skipped",
                    warnings=[*run.warnings, reason],
                    safe_mode=safe,
                )
            items = self.dependencies.enrich(
                run.items,
                max_articles=max_articles,
                query_text=run.query,
                max_chars_per_article=max_chars_per_article,
            )
            return self.repository.complete_operation(
                run.id,
                operation_id,
                stage="enriched",
                items=items,
                safe_mode=False,
            )
        except Exception as exc:
            self.repository.fail_operation(run.id, operation_id, str(exc))
            raise

    def digest(
        self,
        run_id: str,
        *,
        performance_mode: str,
        selected_model: str,
    ) -> NewsRun:
        operation_id = new_id("news_digest")
        run = self.repository.acquire_operation(
            run_id,
            operation_id,
            expected_stages=("searched", "enriched", "enrich_skipped"),
        )
        try:
            digest, source_block, coverage, warnings = self.dependencies.digest(
                run.items,
                query_text=run.query,
                performance_mode=performance_mode,
                selected_model=selected_model,
            )
            return self.repository.complete_operation(
                run.id,
                operation_id,
                stage="digested",
                digest=digest,
                source_block=source_block,
                article_coverage=coverage,
                warnings=[*run.warnings, *warnings],
            )
        except Exception as exc:
            self.repository.fail_operation(run.id, operation_id, str(exc))
            raise

    def discuss(
        self,
        run_id: str,
        *,
        group_thread_id: str | None,
        interaction_mode: str,
        performance_mode: str,
        selected_model: str,
    ) -> NewsRun:
        operation_id = new_id("news_discuss")
        run = self.repository.acquire_operation(
            run_id, operation_id, expected_stages=("digested",)
        )
        try:
            if (
                run.group_thread_id
                and group_thread_id
                and run.group_thread_id != group_thread_id
            ):
                raise ValueError(
                    "NewsRun is already reserved for another Group thread"
                )
            thread = self.group_service.ensure_thread(
                run.group_thread_id or group_thread_id
            )
            run = self.repository.reserve_group_thread(
                run.id, operation_id, thread.id
            )
            discussion, _ = self.dependencies.discuss(
                run.digest,
                interaction_mode=interaction_mode,
                performance_mode=performance_mode,
                selected_model=selected_model,
                source_block=run.source_block,
                session_id=thread.id,
                persist_group=False,
            )
            thread = self.group_service.append_news_bundle(
                thread_id=thread.id,
                source_block=run.source_block,
                discussion=discussion,
                news_run_id=run.id,
            )
            return self.repository.complete_operation(
                run.id,
                operation_id,
                stage="discussed",
                discussion=discussion,
                group_thread_id=thread.id,
                completed=True,
            )
        except Exception as exc:
            self.repository.fail_operation(run.id, operation_id, str(exc))
            raise

    def get(self, run_id: str) -> NewsRun:
        run = self.repository.get(run_id)
        if run is None:
            raise ValueError(f"NewsRun not found: {run_id}")
        return run

    def list(self, *, limit: int = 20) -> list[NewsRun]:
        return self.repository.list(limit=limit)
