"""Runtime repository factory used by application services."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.github_snapshot_repository import GitHubSnapshotRepository
from src.repositories.group_repository import GroupRepository
from src.repositories.learning_closure_repository import LearningClosureRepository
from src.repositories.learning_truth_repository import LearningTruthRepository
from src.repositories.news_repository import NewsRepository
from src.repositories.memory_repository import MemoryRepository
from src.repositories.pedagogy_eval_repository import PedagogyEvalRepository
from src.repositories.provider_cache_repository import ProviderCacheRepository
from src.repositories.session_navigation_repository import SessionNavigationRepository
from src.repositories.thread_summary_repository import ThreadSummaryRepository
from src.repositories.tool_repository import ToolRepository
from src.repositories.web_lookup_repository import WebLookupRepository
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.rag_repository import RagRepository

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_DB = ROOT / "logs" / "runtime" / "study_agent.db"
DEFAULT_CURRENT_DIR = ROOT / "logs" / "current"
DEFAULT_ARCHIVE_DIR = ROOT / "logs" / "sessions"
DEFAULT_GROUP_FILE = ROOT / "chat" / "wechat_group.md"
DEFAULT_GROUP_UNREAD_FILE = ROOT / "chat" / "wechat_unread.md"
DEFAULT_GROUP_STATE_FILE = ROOT / "chat" / "wechat_state.md"
DEFAULT_GROUP_ARCHIVE_DIR = ROOT / "chat" / "archive"


def runtime_database_path() -> Path:
    configured = os.getenv("STUDY_AGENT_RUNTIME_DB", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_RUNTIME_DB


def runtime_current_dir() -> Path:
    configured = os.getenv("STUDY_AGENT_CURRENT_EXPORT_DIR", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_CURRENT_DIR


def runtime_archive_dir() -> Path:
    configured = os.getenv("STUDY_AGENT_ARCHIVE_EXPORT_DIR", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_ARCHIVE_DIR


@lru_cache(maxsize=1)
def get_runtime_repository() -> RuntimeRepository:
    return RuntimeRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_rag_repository() -> RagRepository:
    return RagRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_github_snapshot_repository() -> GitHubSnapshotRepository:
    return GitHubSnapshotRepository(get_rag_repository())


@lru_cache(maxsize=1)
def get_provider_cache_repository() -> ProviderCacheRepository:
    return ProviderCacheRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_github_work_item_service():
    from src.web.github_history import GitHubHistoryService
    from src.web.github_paginated_work_items import PaginatedGitHubWorkItemService

    return PaginatedGitHubWorkItemService(
        GitHubHistoryService(),
        cache_repository=get_provider_cache_repository(),
    )


@lru_cache(maxsize=1)
def get_github_change_impact_service():
    from src.web.github_change_impact import GitHubChangeImpactService
    from src.web.github_history import GitHubHistoryService

    return GitHubChangeImpactService(
        GitHubHistoryService(),
        get_github_snapshot_service(),
        get_provider_cache_repository(),
    )


@lru_cache(maxsize=1)
def get_group_repository() -> GroupRepository:
    return GroupRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_news_repository() -> NewsRepository:
    return NewsRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_memory_repository() -> MemoryRepository:
    return MemoryRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_learning_closure_repository() -> LearningClosureRepository:
    return LearningClosureRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_learning_truth_repository() -> LearningTruthRepository:
    return LearningTruthRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_thread_summary_repository() -> ThreadSummaryRepository:
    return ThreadSummaryRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_session_navigation_repository() -> SessionNavigationRepository:
    return SessionNavigationRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_tool_repository() -> ToolRepository:
    return ToolRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_web_lookup_repository() -> WebLookupRepository:
    return WebLookupRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_pedagogy_eval_repository() -> PedagogyEvalRepository:
    return PedagogyEvalRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_github_snapshot_service():
    from src.application.github_snapshot_service import GitHubSnapshotService

    return GitHubSnapshotService(get_github_snapshot_repository())


@lru_cache(maxsize=1)
def get_learning_source_evidence_service():
    from src.application.github_graph_service import graph_service_for
    from src.application.learning_source_evidence import LearningSourceEvidenceService

    snapshot_service = get_github_snapshot_service()
    return LearningSourceEvidenceService(
        snapshot_service,
        graph_service_for(snapshot_service),
    )


@lru_cache(maxsize=1)
def get_web_tool_agent():
    from src.tools.persistent_web_agent import PersistentWebToolAgent
    from src.web.persistent_tool_gateway import PersistentGeneralWebGateway
    from src.web.semantic_recovery import configured_completion

    return PersistentWebToolAgent(
        gateway=PersistentGeneralWebGateway(
            get_github_snapshot_service(),
            work_item_service=get_github_work_item_service(),
        ),
        research_service=get_web_lookup_service(),
        semantic_completion=configured_completion,
    )


@lru_cache(maxsize=1)
def get_chat_service():
    from src.application.chat_service import ChatDependencies
    from src.application.policy_chat_service import ExternalDataPolicyChatService
    from src.pedagogy.evaluation import LLMSemanticEvaluator
    from src.task_contract import (
        TaskAwarePedagogyEngine,
        TaskAwarePedagogyEvaluationService,
        route_request_with_task_contract,
    )

    return ExternalDataPolicyChatService(
        get_runtime_repository(),
        ChatDependencies(
            route_request=route_request_with_task_contract,
            pedagogy_engine=TaskAwarePedagogyEngine(),
            pedagogy_evaluation=TaskAwarePedagogyEvaluationService(
                LLMSemanticEvaluator()
            ),
            resolve_web_tools=get_web_tool_agent().resolve,
        ),
    )


@lru_cache(maxsize=1)
def get_rag_run_service():
    from src.application.rag_run_service import RagRunService

    return RagRunService(get_rag_repository())


@lru_cache(maxsize=1)
def get_session_attachment_repository():
    from src.repositories.session_attachment_repository import (
        SessionAttachmentRepository,
    )

    return SessionAttachmentRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_session_attachment_service():
    """G14 temporary attachment service with gated vision description."""
    from src.application.session_attachment_service import (
        SessionAttachmentService,
    )

    def vision_enabled() -> bool:
        from src.application.helpers import load_frontend_settings

        return bool(load_frontend_settings().get("attachment_vision_enabled"))

    def vision_describer(path):
        from src.application.attachment_vision import (
            describe_image_with_deepseek,
        )

        return describe_image_with_deepseek(path)

    return SessionAttachmentService(
        get_session_attachment_repository(),
        vision_describer=vision_describer,
        vision_enabled=vision_enabled,
    )


@lru_cache(maxsize=1)
def get_session_service():
    from src.application.session_service import SessionService

    service = SessionService(
        get_runtime_repository(),
        summary_repository=get_thread_summary_repository(),
        navigation_repository=get_session_navigation_repository(),
        current_dir=runtime_current_dir(),
        archive_dir=runtime_archive_dir(),
        attachment_purger=lambda session_id: (
            get_session_attachment_service().purge_thread(session_id)
        ),
    )
    # G12 decision 15: queued "archive after cancel" intents survive restarts;
    # drain any that became due while the process was down.
    try:
        service.process_pending_archives()
    except Exception:  # pragma: no cover - startup must not fail on this
        import logging

        logging.getLogger(__name__).warning(
            "Startup archive-queue sweep failed", exc_info=True
        )
    return service


@lru_cache(maxsize=1)
def get_group_service():
    from src.application.group_chat_service import GroupChatService
    from src.application.group_chat_service import GroupDependencies

    return GroupChatService(
        get_group_repository(),
        group_file=DEFAULT_GROUP_FILE,
        unread_file=DEFAULT_GROUP_UNREAD_FILE,
        state_file=DEFAULT_GROUP_STATE_FILE,
        archive_dir=DEFAULT_GROUP_ARCHIVE_DIR,
        dependencies=GroupDependencies(
            resolve_web_tools=get_web_tool_agent().resolve,
        ),
    )


@lru_cache(maxsize=1)
def get_news_service():
    from src.application.news_service import NewsService

    return NewsService(get_news_repository(), get_group_service())


@lru_cache(maxsize=1)
def get_memory_service():
    from src.application.memory_service import MemoryService

    return MemoryService(get_memory_repository())


@lru_cache(maxsize=1)
def get_learning_closure_truth_service():
    from src.application.learning_closure_truth import LearningClosureTruthService

    return LearningClosureTruthService(
        get_learning_truth_repository(),
        get_learning_source_evidence_service(),
        get_pedagogy_eval_repository(),
    )


@lru_cache(maxsize=1)
def get_learning_closure_service():
    from src.application.learning_closure_service import LearningClosureService

    return LearningClosureService(
        get_learning_closure_repository(),
        get_session_service(),
        get_memory_service(),
        evaluation_repository=get_pedagogy_eval_repository(),
        learning_truth_committer=get_learning_closure_truth_service(),
    )


@lru_cache(maxsize=1)
def get_learning_outcome_commit_service():
    from src.application.learning_outcome_commit import LearningOutcomeCommitService

    return LearningOutcomeCommitService(get_learning_truth_repository())


@lru_cache(maxsize=1)
def get_learning_semantic_closure_service():
    from src.application.learning_semantic_closure import LearningSemanticClosureService

    return LearningSemanticClosureService(get_learning_truth_repository())


@lru_cache(maxsize=1)
def get_learning_revalidation_service():
    from src.application.learning_freshness import LearningFreshnessService
    from src.application.learning_outcome_commit import LearningOutcomeCommitService
    from src.application.learning_revalidation import LearningRevalidationService
    from src.application.learning_source_evidence import LearningSourceEvidenceService
    from src.web.github_freshness import (
        GitHubFreshnessBlobReader,
        GitHubFreshnessHeadResolver,
    )

    truth = get_learning_truth_repository()
    source_evidence = LearningSourceEvidenceService(get_github_snapshot_service())
    freshness = LearningFreshnessService(
        head_resolver=GitHubFreshnessHeadResolver(),
        blob_reader=GitHubFreshnessBlobReader(),
    )
    return LearningRevalidationService(
        truth,
        source_evidence_service=source_evidence,
        commit_service=LearningOutcomeCommitService(truth),
        freshness_service=freshness,
    )


@lru_cache(maxsize=1)
def get_learning_resume_service():
    from src.application.learning_freshness import LearningFreshnessService
    from src.application.learning_resume import LearningResumeService
    from src.web.github_freshness import (
        GitHubFreshnessBlobReader,
        GitHubFreshnessHeadResolver,
    )

    return LearningResumeService(
        get_learning_truth_repository(),
        freshness_evaluator=LearningFreshnessService(
            head_resolver=GitHubFreshnessHeadResolver(),
            blob_reader=GitHubFreshnessBlobReader(),
        ),
    )


@lru_cache(maxsize=1)
def get_learner_model_service():
    from src.application.learner_model import LearnerModelService
    from src.memory import read_memory_file

    return LearnerModelService(
        get_learning_truth_repository(),
        get_pedagogy_eval_repository(),
        read_confirmed_profile=lambda: read_memory_file("learner_profile.md"),
    )


@lru_cache(maxsize=1)
def get_learning_review_service():
    from src.application.learning_review import LearningReviewService

    return LearningReviewService(get_learning_truth_repository())


@lru_cache(maxsize=1)
def get_web_lookup_service():
    from src.application.research_web_lookup_dispatch import (
        ClaimEngineDispatchWebLookupService,
    )

    return ClaimEngineDispatchWebLookupService(get_web_lookup_repository())


@lru_cache(maxsize=1)
def get_tool_service():
    from src import api
    from src.api.app import TOOL_REGISTRY
    from src.application.tool_service import ToolService
    from src.workflows.store import WorkflowStore

    return ToolService(
        get_tool_repository(),
        TOOL_REGISTRY,
        workflow_store_factory=lambda: WorkflowStore(api.WORKFLOW_DIR),
    )


def reset_runtime_repository_cache() -> None:
    get_web_tool_agent.cache_clear()
    get_github_work_item_service.cache_clear()
    get_github_change_impact_service.cache_clear()
    get_provider_cache_repository.cache_clear()
    get_learning_source_evidence_service.cache_clear()
    get_github_snapshot_service.cache_clear()
    get_github_snapshot_repository.cache_clear()
    get_learner_model_service.cache_clear()
    get_learning_review_service.cache_clear()
    get_learning_resume_service.cache_clear()
    get_learning_semantic_closure_service.cache_clear()
    get_learning_outcome_commit_service.cache_clear()
    get_learning_closure_truth_service.cache_clear()
    get_learning_truth_repository.cache_clear()
    get_learning_closure_service.cache_clear()
    get_learning_closure_repository.cache_clear()
    get_thread_summary_repository.cache_clear()
    get_session_navigation_repository.cache_clear()
    get_web_lookup_service.cache_clear()
    get_tool_service.cache_clear()
    get_news_service.cache_clear()
    get_memory_service.cache_clear()
    get_group_service.cache_clear()
    get_chat_service.cache_clear()
    get_rag_run_service.cache_clear()
    get_session_service.cache_clear()
    get_group_repository.cache_clear()
    get_news_repository.cache_clear()
    get_memory_repository.cache_clear()
    get_tool_repository.cache_clear()
    get_web_lookup_repository.cache_clear()
    get_pedagogy_eval_repository.cache_clear()
    get_runtime_repository.cache_clear()
    get_rag_repository.cache_clear()
