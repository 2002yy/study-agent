"""API package — FastAPI application and routes.

Re-exports symbols commonly monkeypatched by tests for backward
compatibility. Tests do ``monkeypatch.setattr(api, "...")`` so
the package must carry these as direct attributes.
"""

from .app import app

# ── Models ─────────────────────────────────────────────────────────────
from .models.chat import (ChatMessage, ChatRequest, ChatResponse,
                           CommitTurnRequest, CommitTurnResponse)
from .models.common import (HealthResponse, RoleListResponse, RoleResponse,
                             SessionArchiveResponse, SessionDetailResponse,
                             SessionListResponse, SessionNewResponse,
                             ToolInvocationRequest, ToolInvocationResponse,
                             ToolListResponse, WorkflowListResponse,
                             WorkflowRunResponse)
from .models.memory import (MemoryCommitResponse, MemoryPreviewItem,
                             MemoryPreviewRequest, MemoryPreviewResponse,
                             MemoryStatusResponse, MemoryUpdate)
from .models.news import (NewsDigestRequest, NewsDigestResponse,
                           NewsDiscussRequest, NewsDiscussResponse,
                           NewsEnrichRequest, NewsEnrichResponse,
                           NewsLookupRequest, NewsLookupResponse,
                           NewsSearchRequest, NewsSearchResponse,
                           NewsStageSearchRequest, NewsStageSearchResponse)
from .models.rag import (LocalKnowledgeRequest, LocalKnowledgeResponse,
                          RagIndexRequest, RagIndexResponse,
                          RagQueryRequest, RagQueryResponse,
                          RagStatusResponse)
from .models.settings import RuntimeSettingsPatch, RuntimeSettingsResponse
from .models.wechat import (WechatMessageRequest, WechatMessageResponse,
                             WechatOpeningRequest, WechatSearchRequest,
                             WechatSearchResponse, WechatStateResponse)

# ── Path constants ─────────────────────────────────────────────────────
from src.application.helpers import (
    CURRENT_SESSION_DIR_DEFAULT as CURRENT_SESSION_DIR,
    FRONTEND_SETTINGS_PATH_DEFAULT as FRONTEND_SETTINGS_PATH,
    MEMORY_DIR_DEFAULT as MEMORY_DIR,
    RAG_UPLOAD_DIR_DEFAULT as RAG_UPLOAD_DIR,
    SESSION_DIR_DEFAULT as SESSION_DIR,
)
from src.workflows.store import DEFAULT_WORKFLOW_DIR as WORKFLOW_DIR

# ── Application helpers (direct attribute access for monkeypatch) ──────
from src.application.helpers import (
    extract_latest_section,
    find_session_file,
    load_frontend_settings,
    memory_file_row,
    memory_target_path,
    memory_update_action,
    memory_update_preview_text,
    messages_from_session_entries,
    news_result_payload,
    parse_archived_session_messages,
    parse_current_session_messages,
    parse_session_turn_snapshots,
    prepare_chat_context,
    previous_assistant_role,
    request_model_profile,
    request_performance_mode,
    role_payload,
    runtime_modes_for_request,
    runtime_settings_options,
    runtime_settings_payload,
    session_file_rows,
    session_settings_from_request,
    session_snapshot_from_entries,
    session_snapshot_from_raw,
    sse_event,
    stream_usage_payload,
    unique_upload_path,
    validate_choice,
    wechat_state_payload,
    write_frontend_settings,
)

# Legacy underscore-prefixed aliases for tests that access these directly
_memory_file_row = memory_file_row
_previous_assistant_role = previous_assistant_role
_extract_latest_section = extract_latest_section
_unique_upload_path = unique_upload_path
_find_session_file = find_session_file
_memory_target_path = memory_target_path
_memory_update_action = memory_update_action
_memory_update_preview_text = memory_update_preview_text
_messages_from_session_entries = messages_from_session_entries
_parse_archived_session_messages = parse_archived_session_messages
_parse_current_session_messages = parse_current_session_messages
_parse_session_turn_snapshots = parse_session_turn_snapshots
_session_file_rows = session_file_rows
_session_snapshot_from_entries = session_snapshot_from_entries
_session_snapshot_from_raw = session_snapshot_from_raw
_wechat_state_payload = wechat_state_payload
_runtime_settings_payload = runtime_settings_payload
_runtime_settings_options = runtime_settings_options
_role_payload = role_payload
_news_result_payload = __import__("src.application.helpers").application.helpers.news_result_payload
_prepare_chat_context = prepare_chat_context
_request_performance_mode = request_performance_mode
_request_model_profile = request_model_profile
_runtime_modes_for_request = runtime_modes_for_request
_sse_event = sse_event
_stream_usage_payload = stream_usage_payload
_validate_choice = validate_choice
_session_settings_from_request = session_settings_from_request
_load_frontend_settings = load_frontend_settings
_write_frontend_settings = write_frontend_settings

# ── Proxy commonly-patched functions from source modules ───────────────
# Tests do monkeypatch.setattr(api, name, ...), so these must be
# direct attributes on the package.
from src.llm_client import chat, stream_chat
from src.memory import read_memory_bundle, read_memory_file
from src.mode_manager import (
    is_memory_write_allowed,
    load_runtime_modes,
    set_memory_mode,
    update_debug_mode,
    update_entry_mode,
    update_interaction_mode,
    update_memory_capture,
    update_performance_mode,
    update_safe_mode,
)
from src.news.digest import format_news_source_block
from src.news.rss_fetcher import fetch_news_items, get_last_feed_warnings
from src.performance_budget import chat_max_tokens
from src.rag import build_rag_context, format_rag_sources, index_documents
from src.rag.backends import get_vector_backend_from_env
from src.rag.index import load_rag_index
from src.rag.service import (
    append_documents_to_index_with_stages,
    build_rag_debug,
    index_documents_with_stages,
    search_documents,
)
from src.role_manager import build_role_prompt, list_roles, load_role
from src.router import route_request
from src.safe_writer import safe_write_text
from src.session_logger import (
    flush_current_session,
    get_or_create_session,
    get_session_entries,
    init_session,
    log,
    save as archive_session_log,
    set_wechat_interactive,
    set_wechat_status,
    set_wechat_unread_cleared,
)
from src.tools.local_knowledge import retrieve_local_knowledge
from src.wechat_generator import (
    generate_interactive_wechat_reply,
    generate_interactive_wechat_reply_stream,
    generate_wechat_opening,
)
from src.wechat_service import (
    run_digest_stage,
    run_discussion_stage,
    run_enrich_stage,
    run_news_round,
    run_search_stage,
)
from src.wechat_state import (
    append_user_and_interactive_group_reply,
    count_wechat_messages,
    has_wechat_group_started,
    has_wechat_unread,
    mark_wechat_read,
    read_wechat_group,
    read_wechat_state,
    read_wechat_unread,
    reset_wechat_group,
    search_wechat,
    start_wechat_group_with_opening,
    summarize_wechat,
    update_wechat_join_state,
)
from src.workflows.store import WorkflowStore
