from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src import memory_writer
from src.context_builder import build_messages
from src.llm_client import chat
from src.memory import read_memory_bundle
from src.mode_manager import is_memory_write_allowed, load_runtime_modes
from src.performance_budget import chat_max_tokens
from src.rag import build_rag_context, format_rag_sources, index_documents
from src.rag.backends import get_vector_backend_from_env
from src.rag.eval import RagEvalCase, evaluate_case
from src.rag.index import DEFAULT_RAG_INDEX_PATH, load_rag_index
from src.rag.service import build_rag_debug, search_documents
from src.role_manager import load_role
from src.router import route_request
from src.session_logger import flush_current_session, get_or_create_session, init_session, log
from src.tools.local_knowledge import retrieve_local_knowledge
from src.tools.registry import create_default_tool_registry
from src.workflows.store import DEFAULT_WORKFLOW_DIR, WorkflowStore

ROOT = Path(__file__).resolve().parent.parent
RAG_UPLOAD_DIR = ROOT / "logs" / "rag_uploads"
SESSION_DIR = ROOT / "logs" / "sessions"
CURRENT_SESSION_DIR = ROOT / "logs" / "current"
WORKFLOW_DIR = DEFAULT_WORKFLOW_DIR


class HealthResponse(BaseModel):
    status: str
    service: str
    rag_index_exists: bool


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


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="study-agent",
        rag_index_exists=DEFAULT_RAG_INDEX_PATH.exists(),
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
