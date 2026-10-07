"""FastAPI application — middleware, CORS, security, mounting.

This is the application assembly point.
Routes are registered on the `app` instance from their respective route modules.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.tools.registry import create_default_tool_registry

from .cors import (
    add_cors_headers,
    build_cors_preflight_response,
    is_cors_preflight,
    resolve_cors_policy,
)

ROOT = Path(__file__).resolve().parent.parent.parent
ASSETS_DIR = ROOT / "assets"

app = FastAPI(title="Study Agent API", version="0.1.0")
if ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

TOOL_REGISTRY = create_default_tool_registry()

# Register all route modules (each module's router is auto-included on import)
from .routes.health_routes import router as _health_router
from .routes.settings_routes import router as _settings_router
from .routes.memory_routes import router as _memory_router
from .routes.learning_closure_routes import router as _learning_closure_router
from .routes.tool_routes import router as _tool_router
from .routes.session_routes import router as _session_router
from .routes.session_attachment_routes import (
    router as _session_attachment_router,
)
from .routes.wechat_routes import router as _wechat_router
from .routes.news_routes import router as _news_router
from .routes.rag_routes import router as _rag_router
from .routes.chat_routes import router as _chat_router
from .routes.web_lookup_routes import router as _web_lookup_router
from .routes.reading_routes import router as _reading_router
from .routes.github_routes import router as _github_router
from .routes.github_review_routes import router as _github_review_router

app.include_router(_health_router)
app.include_router(_settings_router)
app.include_router(_memory_router)
app.include_router(_learning_closure_router)
app.include_router(_tool_router)
app.include_router(_session_router)
app.include_router(_session_attachment_router)
app.include_router(_wechat_router)
app.include_router(_news_router)
app.include_router(_rag_router)
app.include_router(_chat_router)
app.include_router(_web_lookup_router)
app.include_router(_reading_router)
app.include_router(_github_router)
app.include_router(_github_review_router)

# ── Security helpers ──────────────────────────────────────────────────


def _api_token() -> str:
    return os.getenv("STUDY_AGENT_API_TOKEN", "").strip()


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
    cors_policy = resolve_cors_policy()
    origin = request.headers.get("origin", "")

    if is_cors_preflight(request):
        return build_cors_preflight_response(request, cors_policy)

    public_path = request.url.path == "/health" or request.url.path.startswith("/assets/")
    if not public_path and not _is_authorized(request):
        response = JSONResponse({"detail": "Missing or invalid API token"}, status_code=401)
        add_cors_headers(response, origin, cors_policy)
        return response

    response = await call_next(request)
    add_cors_headers(response, origin, cors_policy)
    return response
