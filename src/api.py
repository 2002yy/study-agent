from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src import memory_writer
from src.constants import (
    ATMOS_LABELS,
    ATMOS_OPTIONS,
    ENTRY_LABELS,
    ENTRY_OPTIONS,
    MODE_LABELS,
    MODE_OPTIONS,
    MODEL_LABELS,
    MODEL_OPTIONS,
    PERFORMANCE_OPTIONS,
    PERF_LABELS,
    ROLE_LABELS,
    ROLE_OPTIONS,
)
from src.context_builder import build_messages
from src.llm_client import chat
from src.memory import CONTEXT_FILE_GROUPS, MEMORY_DIR, read_memory_bundle, read_memory_file
from src.mode_manager import (
    get_runtime_config_warnings,
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
from src.performance_budget import chat_max_tokens
from src.rag import build_rag_context, format_rag_sources, index_documents
from src.rag.backends import get_vector_backend_from_env
from src.rag.eval import RagEvalCase, evaluate_case
from src.rag.index import DEFAULT_RAG_INDEX_PATH, load_rag_index
from src.rag.service import build_rag_debug, search_documents
from src.role_manager import list_roles, load_role
from src.router import route_request
from src.safe_writer import safe_write_text
from src.session_logger import flush_current_session, get_or_create_session, init_session, log
from src.tools.local_knowledge import retrieve_local_knowledge
from src.tools.registry import create_default_tool_registry
from src.workflows.store import DEFAULT_WORKFLOW_DIR, WorkflowStore

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
FRONTEND_SETTINGS_PATH = CONFIG_DIR / "frontend_settings.yaml"
RAG_UPLOAD_DIR = ROOT / "logs" / "rag_uploads"
SESSION_DIR = ROOT / "logs" / "sessions"
CURRENT_SESSION_DIR = ROOT / "logs" / "current"
WORKFLOW_DIR = DEFAULT_WORKFLOW_DIR

DEFAULT_FRONTEND_SETTINGS = {
    "selected_role": "auto",
    "selected_mode": "auto",
    "selected_model": "auto",
    "rag_enabled": True,
    "rag_retrieval_mode": "hybrid",
    "rag_top_k": 3,
    "rag_min_score": 0.01,
}


class HealthResponse(BaseModel):
    status: str
    service: str
    rag_index_exists: bool


class RuntimeSettingsPatch(BaseModel):
    selected_role: str | None = None
    selected_mode: str | None = None
    selected_model: str | None = None
    relationship_mode: str | None = None
    entry_mode: str | None = None
    performance_mode: str | None = None
    memory_mode: str | None = None
    debug_mode: bool | None = None
    safe_mode: bool | None = None
    wechat_memory_capture_enabled: bool | None = None
    rag_enabled: bool | None = None
    rag_retrieval_mode: str | None = None
    rag_top_k: int | None = Field(default=None, ge=1, le=20)
    rag_min_score: float | None = Field(default=None, ge=0)


class RuntimeSettingsResponse(BaseModel):
    settings: dict[str, Any]
    options: dict[str, Any]
    runtime_profile: dict[str, Any]
    warnings: list[str]


class RoleListResponse(BaseModel):
    roles: list[dict[str, Any]]


class RoleResponse(BaseModel):
    id: str
    label: str
    prompt: str
    summary: str


class MemoryStatusResponse(BaseModel):
    writable: bool
    memory_mode: str
    safe_mode: bool
    reason: str
    context_mode: str
    groups: dict[str, list[str]]
    files: list[dict[str, Any]]


class RagIndexRequest(BaseModel):
    paths: list[str] = Field(min_length=1)
    index_path: str | None = None
    max_chars: int = Field(default=900, gt=0, le=10_000)
    overlap_chars: int = Field(default=120, ge=0, le=5_000)


class RagIndexResponse(BaseModel):
    documents: int
    chunks: int
    index_path: str


class RagStatusResponse(BaseModel):
    index_path: str
    index_exists: bool
    documents: int = 0
    chunks: int = 0
    vector_backend: dict[str, Any]


class RagQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    index_path: str | None = None
    top_k: int = Field(default=5, gt=0, le=20)
    min_score: float = Field(default=0.01, ge=0)
    retrieval_mode: str = Field(default="hybrid")
    context_max_chars: int = Field(default=3000, gt=0, le=20_000)
    expected_sources: list[str] = Field(default_factory=list)
    expected_terms: list[str] = Field(default_factory=list)


class RagQueryResponse(BaseModel):
    query: str
    retrieval_mode: str
    result_count: int
    context: str
    sources: str
    results: list[dict[str, Any]]
    debug: dict[str, Any]
    evaluation: dict[str, Any] | None = None


class LocalKnowledgeRequest(BaseModel):
    query: str = Field(min_length=1)
    enabled: bool = True
    force: bool = False
    index_path: str | None = None
    top_k: int = Field(default=3, gt=0, le=20)
    min_score: float = Field(default=0.01, ge=0)
    retrieval_mode: str = Field(default="hybrid")
    context_max_chars: int = Field(default=3000, gt=0, le=20_000)
    allow_rewrite: bool = True
    weak_score_threshold: float = Field(default=0.05, ge=0)


class LocalKnowledgeResponse(BaseModel):
    status: str
    query: str
    retrieval_mode: str
    reason: str
    context: str
    sources: str
    result_count: int
    results: list[dict[str, Any]]
    debug: dict[str, Any]
    attempts: list[dict[str, Any]]
    rewritten_query: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    user_input: str = Field(min_length=1)
    selected_role: str = "auto"
    selected_mode: str = "auto"
    selected_model: str = "auto"
    relationship_mode: str = "standard"
    context_mode: str | None = None
    chat_history: list[ChatMessage] = Field(default_factory=list)
    session_id: str | None = None
    rag_enabled: bool = False
    rag_top_k: int = Field(default=3, gt=0, le=20)
    rag_retrieval_mode: str = "hybrid"


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    route: dict[str, Any]
    rag: dict[str, Any]


class MemoryUpdate(BaseModel):
    target: str
    content: str = Field(min_length=1)
    append: bool = True
    learner_pending: bool = False


class MemoryPreviewRequest(BaseModel):
    updates: list[MemoryUpdate] = Field(min_length=1)


class MemoryPreviewItem(BaseModel):
    target: str
    path: str
    action: str
    allowed: bool
    preview: str


class MemoryPreviewResponse(BaseModel):
    writable: bool
    memory_mode: str
    safe_mode: bool
    updates: list[MemoryPreviewItem]


class MemoryCommitResponse(BaseModel):
    writable: bool
    results: list[dict[str, str]]


class SessionListResponse(BaseModel):
    sessions: list[dict[str, Any]]


class ToolInvocationRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None


class ToolInvocationResponse(BaseModel):
    tool_name: str
    status: str
    output: dict[str, Any]
    reason: str
    elapsed_ms: int
    run_id: str


class ToolListResponse(BaseModel):
    tools: list[dict[str, Any]]


class WorkflowListResponse(BaseModel):
    runs: list[dict[str, Any]]


class WorkflowRunResponse(BaseModel):
    run: dict[str, Any]


app = FastAPI(title="Study Agent API", version="0.1.0")
TOOL_REGISTRY = create_default_tool_registry()


def _api_token() -> str:
    return os.getenv("STUDY_AGENT_API_TOKEN", "").strip()


def _allowed_cors_origins() -> set[str]:
    raw = os.getenv("STUDY_AGENT_CORS_ORIGINS", "")
    return {origin.strip() for origin in raw.split(",") if origin.strip()}


def _is_cors_origin_allowed(origin: str, allowed_origins: set[str]) -> bool:
    return "*" in allowed_origins or origin in allowed_origins


def _add_cors_headers(response: Response, origin: str, allowed_origins: set[str]) -> None:
    if not origin or not _is_cors_origin_allowed(origin, allowed_origins):
        return
    response.headers["Access-Control-Allow-Origin"] = "*" if "*" in allowed_origins else origin
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type,X-Study-Agent-Token"
    if "*" not in allowed_origins:
        response.headers["Vary"] = "Origin"


def _request_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-study-agent-token", "").strip()


def _is_authorized(request: Request) -> bool:
    required_token = _api_token()
    if not required_token:
        return True
    supplied_token = _request_token(request)
    return bool(supplied_token) and secrets.compare_digest(supplied_token, required_token)


@app.middleware("http")
async def api_security_middleware(request: Request, call_next):
    allowed_origins = _allowed_cors_origins()
    origin = request.headers.get("origin", "")

    if request.method == "OPTIONS" and request.headers.get("access-control-request-method"):
        if origin and _is_cors_origin_allowed(origin, allowed_origins):
            response = Response(status_code=204)
            _add_cors_headers(response, origin, allowed_origins)
            return response
        return JSONResponse({"detail": "CORS origin not allowed"}, status_code=403)

    if request.url.path != "/health" and not _is_authorized(request):
        response = JSONResponse({"detail": "Missing or invalid API token"}, status_code=401)
        _add_cors_headers(response, origin, allowed_origins)
        return response

    response = await call_next(request)
    _add_cors_headers(response, origin, allowed_origins)
    return response


def _index_path(value: str | None) -> Path:
    return Path(value) if value else DEFAULT_RAG_INDEX_PATH


def _memory_target_path(target: str) -> Path:
    path = memory_writer.MEMORY_TARGETS.get(target)
    if path is None:
        raise HTTPException(status_code=400, detail=f"Unknown memory target: {target}")
    return path


def _memory_update_action(update: MemoryUpdate) -> str:
    if update.append:
        return "append"
    if update.target == "current_focus":
        return "replace"
    raise HTTPException(
        status_code=400,
        detail="append=false is only supported for target current_focus",
    )


def _unique_upload_path(upload_dir: Path, filename: str | None, used_names: set[str]) -> Path:
    raw_name = Path(filename or "document").name or "document"
    raw_path = Path(raw_name)
    stem = raw_path.stem or "document"
    suffix = raw_path.suffix
    candidate = raw_name
    counter = 2
    while candidate in used_names or (upload_dir / candidate).exists():
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    used_names.add(candidate)
    return upload_dir / candidate


def _session_file_rows(directory: Path, kind: str, limit: int) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in directory.glob("*.md"):
        stat = path.stat()
        rows.append(
            {
                "kind": kind,
                "name": path.name,
                "path": str(path),
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    rows.sort(key=lambda row: int(row["mtime_ns"]), reverse=True)
    return rows[:limit]


def _workflow_store() -> WorkflowStore:
    return WorkflowStore(WORKFLOW_DIR)


def _workflow_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run["run_id"],
        "workflow_name": run["workflow_name"],
        "status": run["status"],
        "started_at": run["started_at"],
        "completed_at": run["completed_at"],
        "elapsed_ms": run["elapsed_ms"],
        "event_count": len(run["events"]),
    }


def _frontend_settings_defaults() -> dict[str, Any]:
    return dict(DEFAULT_FRONTEND_SETTINGS)


def _load_frontend_settings() -> dict[str, Any]:
    data: dict[str, Any] = {}
    if FRONTEND_SETTINGS_PATH.is_file():
        try:
            raw = yaml.safe_load(FRONTEND_SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except yaml.YAMLError:
            data = {}
    settings = _frontend_settings_defaults()
    settings.update({key: value for key, value in data.items() if key in settings})
    return _normalize_frontend_settings(settings)


def _write_frontend_settings(settings: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    safe_write_text(
        FRONTEND_SETTINGS_PATH,
        yaml.safe_dump(
            _normalize_frontend_settings(settings),
            allow_unicode=True,
            sort_keys=False,
        ),
    )


def _normalize_frontend_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = _frontend_settings_defaults()
    selected_role = settings.get("selected_role")
    if selected_role in ROLE_OPTIONS:
        normalized["selected_role"] = selected_role
    selected_mode = settings.get("selected_mode")
    if selected_mode in MODE_OPTIONS:
        normalized["selected_mode"] = selected_mode
    selected_model = settings.get("selected_model")
    if selected_model in MODEL_OPTIONS:
        normalized["selected_model"] = selected_model
    normalized["rag_enabled"] = bool(settings.get("rag_enabled", normalized["rag_enabled"]))
    retrieval_mode = settings.get("rag_retrieval_mode")
    if retrieval_mode in {"lexical", "vector", "hybrid", "backend_vector"}:
        normalized["rag_retrieval_mode"] = retrieval_mode
    try:
        normalized["rag_top_k"] = max(1, min(20, int(settings.get("rag_top_k", normalized["rag_top_k"]))))
    except (TypeError, ValueError):
        pass
    try:
        normalized["rag_min_score"] = max(0.0, float(settings.get("rag_min_score", normalized["rag_min_score"])))
    except (TypeError, ValueError):
        pass
    return normalized


def _runtime_settings_options() -> dict[str, Any]:
    return {
        "roles": [{"id": role_id, "label": ROLE_LABELS.get(role_id, role_id)} for role_id in ROLE_OPTIONS],
        "modes": [{"id": mode, "label": MODE_LABELS.get(mode, mode)} for mode in MODE_OPTIONS],
        "models": [{"id": model, "label": MODEL_LABELS.get(model, model)} for model in MODEL_OPTIONS],
        "performance_modes": [
            {"id": mode, "label": PERF_LABELS.get(mode, mode)} for mode in PERFORMANCE_OPTIONS
        ],
        "relationship_modes": [
            {"id": mode, "label": ATMOS_LABELS.get(mode, mode)} for mode in ATMOS_OPTIONS
        ],
        "entry_modes": [{"id": mode, "label": ENTRY_LABELS.get(mode, mode)} for mode in ENTRY_OPTIONS],
        "memory_modes": ["readonly", "preview", "confirm_write", "locked"],
        "retrieval_modes": ["lexical", "vector", "hybrid", "backend_vector"],
    }


def _runtime_settings_payload() -> RuntimeSettingsResponse:
    modes = load_runtime_modes()
    profile = modes.profile
    settings = {
        **_load_frontend_settings(),
        "relationship_mode": modes.relationship_mode,
        "entry_mode": modes.entry_mode,
        "performance_mode": modes.performance_mode,
        "memory_mode": modes.memory_mode,
        "debug_mode": modes.debug_mode,
        "safe_mode": modes.safe_mode,
        "route_mode": modes.route_mode,
        "context_mode": modes.context_mode,
        "current_version": modes.current_version,
        "active_task": modes.active_task,
        "next_version": modes.next_version,
        "wechat_memory_capture_enabled": modes.memory_capture_enabled,
        "wechat_memory_capture_mode": modes.memory_capture_mode,
    }
    return RuntimeSettingsResponse(
        settings=settings,
        options=_runtime_settings_options(),
        runtime_profile=dict(profile.__dict__),
        warnings=list(get_runtime_config_warnings()),
    )


def _validate_choice(value: str, choices: list[str] | tuple[str, ...], label: str) -> str:
    if value not in choices:
        raise HTTPException(status_code=400, detail=f"Invalid {label}: {value}")
    return value


def _role_payload(role_id: str) -> RoleResponse:
    if role_id == "auto":
        return RoleResponse(
            id="auto",
            label=ROLE_LABELS["auto"],
            prompt="",
            summary="自动模式会根据输入内容选择角色，不绑定固定人设。",
        )
    if role_id not in list_roles():
        raise HTTPException(status_code=404, detail=f"Unknown role: {role_id}")
    prompt = load_role(role_id)
    summary = prompt.splitlines()[0][:160] if prompt.splitlines() else prompt[:160]
    return RoleResponse(
        id=role_id,
        label=ROLE_LABELS.get(role_id, role_id),
        prompt=prompt,
        summary=summary,
    )


def _memory_file_row(name: str) -> dict[str, Any]:
    path = MEMORY_DIR / name
    exists = path.is_file()
    content = read_memory_file(name) if exists else ""
    stat = path.stat() if exists else None
    return {
        "name": name,
        "path": str(path),
        "exists": exists,
        "size_bytes": stat.st_size if stat else 0,
        "mtime_ns": stat.st_mtime_ns if stat else 0,
        "preview": content[:1600],
    }


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="study-agent",
        rag_index_exists=DEFAULT_RAG_INDEX_PATH.exists(),
    )


@app.get("/runtime/settings", response_model=RuntimeSettingsResponse)
def get_runtime_settings() -> RuntimeSettingsResponse:
    return _runtime_settings_payload()


@app.patch("/runtime/settings", response_model=RuntimeSettingsResponse)
def patch_runtime_settings(request: RuntimeSettingsPatch) -> RuntimeSettingsResponse:
    frontend_settings = _load_frontend_settings()
    if request.selected_role is not None:
        frontend_settings["selected_role"] = _validate_choice(
            request.selected_role, ROLE_OPTIONS, "selected_role"
        )
    if request.selected_mode is not None:
        frontend_settings["selected_mode"] = _validate_choice(
            request.selected_mode, MODE_OPTIONS, "selected_mode"
        )
    if request.selected_model is not None:
        frontend_settings["selected_model"] = _validate_choice(
            request.selected_model, MODEL_OPTIONS, "selected_model"
        )
    if request.rag_enabled is not None:
        frontend_settings["rag_enabled"] = request.rag_enabled
    if request.rag_retrieval_mode is not None:
        frontend_settings["rag_retrieval_mode"] = _validate_choice(
            request.rag_retrieval_mode,
            ("lexical", "vector", "hybrid", "backend_vector"),
            "rag_retrieval_mode",
        )
    if request.rag_top_k is not None:
        frontend_settings["rag_top_k"] = request.rag_top_k
    if request.rag_min_score is not None:
        frontend_settings["rag_min_score"] = request.rag_min_score
    _write_frontend_settings(frontend_settings)

    if request.relationship_mode is not None:
        update_interaction_mode(
            _validate_choice(request.relationship_mode, ATMOS_OPTIONS, "relationship_mode")
        )
    if request.entry_mode is not None:
        update_entry_mode(_validate_choice(request.entry_mode, ENTRY_OPTIONS, "entry_mode"))
    if request.performance_mode is not None:
        update_performance_mode(
            _validate_choice(request.performance_mode, PERFORMANCE_OPTIONS, "performance_mode")
        )
    if request.memory_mode is not None:
        set_memory_mode(
            _validate_choice(
                request.memory_mode,
                ("readonly", "preview", "confirm_write", "locked"),
                "memory_mode",
            )
        )
    if request.debug_mode is not None:
        update_debug_mode(request.debug_mode)
    if request.safe_mode is not None:
        update_safe_mode(request.safe_mode)
    if request.wechat_memory_capture_enabled is not None:
        update_memory_capture(request.wechat_memory_capture_enabled)
    return _runtime_settings_payload()


@app.get("/roles", response_model=RoleListResponse)
def get_roles() -> RoleListResponse:
    roles = [
        {"id": role_id, "label": ROLE_LABELS.get(role_id, role_id), "summary": _role_payload(role_id).summary}
        for role_id in ROLE_OPTIONS
    ]
    return RoleListResponse(roles=roles)


@app.get("/roles/{role_id}", response_model=RoleResponse)
def get_role(role_id: str) -> RoleResponse:
    return _role_payload(role_id)


@app.get("/memory", response_model=MemoryStatusResponse)
def get_memory_status(context_mode: str | None = None) -> MemoryStatusResponse:
    modes = load_runtime_modes()
    resolved_context_mode = context_mode or modes.context_mode
    if resolved_context_mode not in CONTEXT_FILE_GROUPS:
        raise HTTPException(status_code=400, detail=f"Invalid context_mode: {resolved_context_mode}")
    writable = is_memory_write_allowed(modes)
    file_names = list(dict.fromkeys(CONTEXT_FILE_GROUPS["archive"]))
    files = [_memory_file_row(name) for name in file_names]
    return MemoryStatusResponse(
        writable=writable,
        memory_mode=modes.memory_mode,
        safe_mode=modes.safe_mode,
        reason=modes.profile.memory_write_reason,
        context_mode=resolved_context_mode,
        groups=CONTEXT_FILE_GROUPS,
        files=files,
    )


@app.get("/rag/status", response_model=RagStatusResponse)
def rag_status(index_path: str | None = None) -> RagStatusResponse:
    target = _index_path(index_path)
    documents = 0
    chunks = 0
    if target.exists():
        index = load_rag_index(target)
        documents = len(index.documents)
        chunks = len(index.chunks)
    try:
        backend_status = get_vector_backend_from_env().status().to_dict()
    except Exception as exc:
        backend_status = {
            "name": "unknown",
            "available": False,
            "detail": str(exc),
        }
    return RagStatusResponse(
        index_path=str(target),
        index_exists=target.exists(),
        documents=documents,
        chunks=chunks,
        vector_backend=backend_status,
    )


@app.post("/rag/index", response_model=RagIndexResponse)
def build_rag_index_endpoint(request: RagIndexRequest) -> RagIndexResponse:
    try:
        target = _index_path(request.index_path)
        index = index_documents(
            request.paths,
            index_path=target,
            max_chars=request.max_chars,
            overlap_chars=request.overlap_chars,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RagIndexResponse(
        documents=len(index.documents),
        chunks=len(index.chunks),
        index_path=str(target),
    )


@app.post("/rag/upload", response_model=RagIndexResponse)
async def upload_rag_documents(
    files: list[UploadFile] = File(...),
    index_path: str | None = None,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> RagIndexResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if max_chars <= 0 or max_chars > 10_000:
        raise HTTPException(status_code=400, detail="max_chars out of range")
    if overlap_chars < 0 or overlap_chars > 5_000:
        raise HTTPException(status_code=400, detail="overlap_chars out of range")

    RAG_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    used_names: set[str] = set()
    for uploaded in files:
        target = _unique_upload_path(RAG_UPLOAD_DIR, uploaded.filename, used_names)
        target.write_bytes(await uploaded.read())
        saved_paths.append(target)

    target_index = _index_path(index_path)
    try:
        index = index_documents(
            saved_paths,
            index_path=target_index,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RagIndexResponse(
        documents=len(index.documents),
        chunks=len(index.chunks),
        index_path=str(target_index),
    )


@app.post("/rag/query", response_model=RagQueryResponse)
def query_rag_endpoint(request: RagQueryRequest) -> RagQueryResponse:
    try:
        index = load_rag_index(_index_path(request.index_path))
        results = search_documents(
            index,
            request.query,
            top_k=request.top_k,
            min_score=request.min_score,
            retrieval_mode=request.retrieval_mode,
        )
        debug = build_rag_debug(
            index,
            request.query,
            results,
            retrieval_mode=request.retrieval_mode,
            top_k=request.top_k,
            min_score=request.min_score,
        )
        evaluation = None
        if request.expected_sources:
            evaluation = evaluate_case(
                index,
                RagEvalCase(
                    query=request.query,
                    expected_sources=tuple(request.expected_sources),
                    expected_terms=tuple(request.expected_terms),
                    top_k=request.top_k,
                    retrieval_mode=request.retrieval_mode,
                ),
                min_score=request.min_score,
            ).to_dict()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="RAG index not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RagQueryResponse(
        query=request.query,
        retrieval_mode=request.retrieval_mode,
        result_count=len(results),
        context=build_rag_context(results, max_chars=request.context_max_chars),
        sources=format_rag_sources(results),
        results=[result.to_dict() for result in results],
        debug=debug,
        evaluation=evaluation,
    )


@app.post("/rag", response_model=RagQueryResponse)
def query_rag_alias(request: RagQueryRequest) -> RagQueryResponse:
    return query_rag_endpoint(request)


@app.post("/rag/local-knowledge", response_model=LocalKnowledgeResponse)
def local_knowledge_endpoint(request: LocalKnowledgeRequest) -> LocalKnowledgeResponse:
    result = retrieve_local_knowledge(
        request.query,
        enabled=request.enabled,
        force=request.force,
        index_path=_index_path(request.index_path),
        top_k=request.top_k,
        min_score=request.min_score,
        retrieval_mode=request.retrieval_mode,
        context_max_chars=request.context_max_chars,
        allow_rewrite=request.allow_rewrite,
        weak_score_threshold=request.weak_score_threshold,
    )
    return LocalKnowledgeResponse(**result.to_dict())


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest) -> ChatResponse:
    runtime_modes = load_runtime_modes()
    context_mode = request.context_mode or runtime_modes.context_mode
    route = route_request(
        user_input=request.user_input,
        selected_role=request.selected_role,
        selected_mode=request.selected_mode,
        selected_model=request.selected_model,
        runtime_modes=runtime_modes,
    )
    role_prompt = load_role(route["role"])
    memory_bundle = read_memory_bundle(context_mode)
    rag_result = retrieve_local_knowledge(
        request.user_input,
        enabled=request.rag_enabled,
        top_k=request.rag_top_k,
        retrieval_mode=request.rag_retrieval_mode,
    )
    messages = build_messages(
        user_input=request.user_input,
        role_prompt=role_prompt,
        mode=route["mode"],
        memory_bundle=memory_bundle,
        chat_history=[message.model_dump() for message in request.chat_history],
        relationship_mode=request.relationship_mode,
        runtime_modes=runtime_modes,
        context_mode=context_mode,
        rag_context=rag_result.context,
    )
    reply = chat(
        messages,
        model_profile=route["model_profile"],
        max_tokens=chat_max_tokens(runtime_modes.performance_mode),
        task_name="single_chat",
    )
    session_id = request.session_id or init_session()
    log(
        session_id=session_id,
        role=route["role"],
        mode=route["mode"],
        model=route["model_profile"],
        user_input=request.user_input,
        agent_reply=reply,
        memory_enabled=bool(memory_bundle),
        route_info={**route, "rag_status": rag_result.status},
    )
    flush_current_session(
        session_id,
        performance_mode=runtime_modes.performance_mode,
        debug_mode=runtime_modes.debug_mode,
    )
    return ChatResponse(
        reply=reply,
        session_id=session_id,
        route=route,
        rag=rag_result.to_dict(),
    )


@app.post("/memory/preview", response_model=MemoryPreviewResponse)
def preview_memory_updates(request: MemoryPreviewRequest) -> MemoryPreviewResponse:
    runtime_modes = load_runtime_modes()
    writable = is_memory_write_allowed(runtime_modes)
    items = []
    for update in request.updates:
        target = _memory_target_path(update.target)
        action = _memory_update_action(update)
        prefix = "### 待确认观察\n\n" if update.learner_pending else ""
        preview = f"{prefix}{update.content.strip()}\n"
        items.append(
            MemoryPreviewItem(
                target=update.target,
                path=str(target),
                action=action,
                allowed=writable,
                preview=preview,
            )
        )
    return MemoryPreviewResponse(
        writable=writable,
        memory_mode=runtime_modes.memory_mode,
        safe_mode=runtime_modes.safe_mode,
        updates=items,
    )


@app.post("/memory/commit", response_model=MemoryCommitResponse)
def commit_memory_updates(request: MemoryPreviewRequest) -> MemoryCommitResponse:
    runtime_modes = load_runtime_modes()
    writable = is_memory_write_allowed(runtime_modes)
    if not writable:
        raise HTTPException(
            status_code=403,
            detail={
                "memory_mode": runtime_modes.memory_mode,
                "safe_mode": runtime_modes.safe_mode,
                "reason": runtime_modes.profile.memory_write_reason,
            },
        )
    results = []
    for update in request.updates:
        _memory_target_path(update.target)
        action = _memory_update_action(update)
        if action == "replace":
            path = memory_writer.write_current_focus(update.content.strip())
        else:
            path = memory_writer.append_memory(
                update.target,
                update.content.strip(),
                learner_pending=update.learner_pending,
            )
        results.append({"target": update.target, "action": action, "path": path})
    return MemoryCommitResponse(writable=writable, results=results)


@app.get("/sessions", response_model=SessionListResponse)
def list_sessions(limit: int = 20) -> SessionListResponse:
    safe_limit = max(1, min(limit, 100))
    current = _session_file_rows(CURRENT_SESSION_DIR, "current", safe_limit)
    archived = _session_file_rows(SESSION_DIR, "archived", safe_limit)
    sessions = [*current, *archived]
    sessions.sort(key=lambda row: int(row["mtime_ns"]), reverse=True)
    return SessionListResponse(sessions=sessions[:safe_limit])


@app.post("/sessions/{session_id}/flush")
def flush_session(session_id: str) -> dict[str, Any]:
    get_or_create_session(session_id)
    flushed = flush_current_session(session_id, force=True)
    return {"session_id": session_id, "flushed": flushed}


@app.get("/tools", response_model=ToolListResponse)
def list_tools() -> ToolListResponse:
    return ToolListResponse(tools=[spec.to_dict() for spec in TOOL_REGISTRY.list_specs()])


@app.post("/tools/{tool_name}/preview", response_model=ToolInvocationResponse)
def preview_tool(tool_name: str, request: ToolInvocationRequest) -> ToolInvocationResponse:
    if TOOL_REGISTRY.get_spec(tool_name) is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    result = TOOL_REGISTRY.preview(tool_name, request.args)
    return ToolInvocationResponse(**result.to_dict())


@app.post("/tools/{tool_name}/call", response_model=ToolInvocationResponse)
def call_tool(tool_name: str, request: ToolInvocationRequest) -> ToolInvocationResponse:
    if TOOL_REGISTRY.get_spec(tool_name) is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    result = TOOL_REGISTRY.call_with_audit(
        tool_name,
        request.args,
        store=_workflow_store(),
        run_id=request.run_id,
    )
    return ToolInvocationResponse(**result.to_dict())


@app.get("/workflows/runs", response_model=WorkflowListResponse)
def list_workflow_runs(limit: int = 20) -> WorkflowListResponse:
    safe_limit = max(1, min(limit, 100))
    runs = [run.to_dict() for run in _workflow_store().list_runs(safe_limit)]
    return WorkflowListResponse(runs=[_workflow_summary(run) for run in runs])


@app.get("/workflows/runs/{run_id}", response_model=WorkflowRunResponse)
def get_workflow_run(run_id: str) -> WorkflowRunResponse:
    run = _workflow_store().load_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown workflow run: {run_id}")
    return WorkflowRunResponse(run=run.to_dict())
