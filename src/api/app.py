"""FastAPI application — middleware, CORS, security, mounting.

This is the application assembly point.
Routes are registered on the `app` instance from their respective route modules.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.tools.registry import create_default_tool_registry

ROOT = Path(__file__).resolve().parent.parent.parent
ASSETS_DIR = ROOT / "assets"

app = FastAPI(title="Study Agent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
if ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

TOOL_REGISTRY = create_default_tool_registry()

# Register all route modules (each module's router is auto-included on import)
from .routes.health_routes import router as _health_router
from .routes.settings_routes import router as _settings_router
from .routes.memory_routes import router as _memory_router
from .routes.tool_routes import router as _tool_router
from .routes.session_routes import router as _session_router
from .routes.wechat_routes import router as _wechat_router
from .routes.news_routes import router as _news_router
from .routes.rag_routes import router as _rag_router
from .routes.chat_routes import router as _chat_router
from .routes.web_lookup_routes import router as _web_lookup_router
from .routes.github_routes import router as _github_router
from .routes.github_review_routes import router as _github_review_router

app.include_router(_health_router)
app.include_router(_settings_router)
app.include_router(_memory_router)
app.include_router(_tool_router)
app.include_router(_session_router)
app.include_router(_wechat_router)
app.include_router(_news_router)
app.include_router(_rag_router)
app.include_router(_chat_router)
app.include_router(_web_lookup_router)
app.include_router(_github_router)
app.include_router(_github_review_router)

# ── Security helpers ──────────────────────────────────────────────────


def _api_token() -> str:
    return os.getenv("STUDY_AGENT_API_TOKEN", "").strip()


def _allowed_cors_origins() -> set[str]:
    raw = os.getenv("STUDY_AGENT_CORS_ORIGINS", "")
    if not raw.strip():
        return {
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:4173",
            "http://localhost:4173",
        }
    return {origin.strip() for origin in raw.split(",") if origin.strip()}


def _is_cors_origin_allowed(origin: str, allowed_origins: set[str]) -> bool:
    return "*" in allowed_origins or origin in allowed_origins


def _add_cors_headers(response: Response, origin: str, allowed_origins: set[str]) -> None:
    if not origin or not _is_cors_origin_allowed(origin, allowed_origins):
        return
    response.headers["Access-Control-Allow-Origin"] = "*" if "*" in allowed_origins else origin
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,DELETE,OPTIONS"
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

    public_path = request.url.path == "/health" or request.url.path.startswith("/assets/")
    if not public_path and not _is_authorized(request):
        response = JSONResponse({"detail": "Missing or invalid API token"}, status_code=401)
        _add_cors_headers(response, origin, allowed_origins)
        return response

    response = await call_next(request)
    _add_cors_headers(response, origin, allowed_origins)
    return response
