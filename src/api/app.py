"""FastAPI application — middleware, CORS, security, mounting.

This is the application assembly point.
Routes are registered on the `app` instance from their respective route modules.
"""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
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

@asynccontextmanager
async def _deep_trigger_lifespan(_app: FastAPI):
    """Start the background workers, best effort.

    Two workers, and they are independent: the Deep trigger, and - since
    QD-3e - the persistent research coordinator.

    Deep recovery must never be a condition for serving chat: if the worker cannot start, the
    application still comes up and the next explicit start can retry. Shutdown is bounded and
    never waits out a running Deep call.

    The research coordinator follows the same rule, and it has one more:
    it only starts when an executor has been configured, because an
    executor calls a model and a model call costs money. A coordinator with
    no executor is a worker that scans forever and accomplishes nothing, so
    the production path refuses to start one rather than pretending to be
    alive. A research that was not advanced is still durable - it is in the
    database, and the next start picks it up.
    """

    import logging

    logger = logging.getLogger(__name__)
    if not _api_token():
        logger.warning(
            "STUDY_AGENT_API_TOKEN is not set: every private API request will be "
            "rejected with 401 (code=api_token_not_configured). Set it before "
            "starting the server and paste the same value once in the app's "
            "settings (访问令牌)."
        )
    try:
        from src.application.runtime_repository import get_deep_trigger_runner

        get_deep_trigger_runner().start()
    except Exception:
        logger.exception("deep trigger startup failed")

    coordinator = None
    try:
        from src.application.runtime_repository import get_research_coordinator

        coordinator = get_research_coordinator()
    except Exception:
        logger.exception("research coordinator startup failed")

    try:
        yield
    finally:
        try:
            from src.application.runtime_repository import get_deep_trigger_runner

            get_deep_trigger_runner().stop()
        except Exception:
            logger.exception("deep trigger shutdown failed")
        if coordinator is not None:
            try:
                from src.application.research_production import (
                    stop_research_coordinator,
                )

                stop_research_coordinator(coordinator)
            except Exception:
                logger.exception("research coordinator shutdown failed")



app = FastAPI(title="Study Agent API", version="0.1.0", lifespan=_deep_trigger_lifespan)
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
from .routes.research_routes import router as _research_router
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
app.include_router(_research_router)
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
        # A2: no configured token means no API access, not open access. A shared
        # token cannot be a boundary between users, but its absence must never be
        # read as "this deployment is private". Loopback is not a boundary either
        # (a reverse proxy can make a remote request look local), so the only
        # safe answer without a configured secret is "refuse".
        return False
    supplied_token = _request_token(request)
    return bool(supplied_token) and secrets.compare_digest(supplied_token, required_token)


def _auth_failure(request: Request) -> JSONResponse:
    """401 with a code the client can act on: configure vs. supply the token."""

    if not _api_token():
        detail = "API token is not configured; set STUDY_AGENT_API_TOKEN on the server"
        code = "api_token_not_configured"
    else:
        detail = "Missing or invalid API token"
        code = "api_token_required"
    response = JSONResponse({"detail": detail, "code": code}, status_code=401)
    return response


@app.middleware("http")
async def api_security_middleware(request: Request, call_next):
    cors_policy = resolve_cors_policy()
    origin = request.headers.get("origin", "")

    if is_cors_preflight(request):
        return build_cors_preflight_response(request, cors_policy)

    public_path = request.url.path == "/health" or request.url.path.startswith("/assets/")
    if not public_path and not _is_authorized(request):
        response = _auth_failure(request)
        add_cors_headers(response, origin, cors_policy)
        return response

    response = await call_next(request)
    add_cors_headers(response, origin, cors_policy)
    return response
