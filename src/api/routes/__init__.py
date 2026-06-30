"""Routes package — import all route modules for side-effect (router registration)."""

from .chat_routes import router as chat_router
from .health_routes import router as health_router
from .memory_routes import router as memory_router
from .news_routes import router as news_router
from .rag_routes import router as rag_router
from .session_routes import router as session_router
from .settings_routes import router as settings_router
from .tool_routes import router as tool_router
from .wechat_routes import router as wechat_router
from .web_lookup_routes import router as web_lookup_router

__all__ = [
    "chat_router",
    "health_router",
    "memory_router",
    "news_router",
    "rag_router",
    "session_router",
    "settings_router",
    "tool_router",
    "wechat_router",
    "web_lookup_router",
]
