"""Avatar helpers for chat and WeChat UI."""

import base64
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent.parent
AVATAR_DIR = ROOT / "assets" / "avatars"
BANNER_DIR = ROOT / "assets" / "banners"

TEXT_AVATARS = {
    "march7": "7",
    "keqing": "Q",
    "nahida": "N",
    "firefly": "F",
    "auto": "?",
    "user": "我",
}

ROLE_CLASSES = {
    "march7": "m7",
    "keqing": "kq",
    "nahida": "nh",
    "firefly": "ly",
    "user": "user",
}

ROLE_COLORS = {
    "march7": "#f38ba8",
    "keqing": "#cba6f7",
    "nahida": "#94e2d5",
    "firefly": "#fab387",
    "user": "#6b7280",
}


def avatar_text(role_id: str) -> str:
    return TEXT_AVATARS.get(role_id, "?")


def avatar_class(role_id: str) -> str:
    return ROLE_CLASSES.get(role_id, "")


def get_avatar_path(role_id: str) -> str | None:
    """Return the local avatar image path if it exists."""
    path = AVATAR_DIR / f"{role_id}.png"
    return str(path) if path.is_file() else None


@lru_cache(maxsize=32)
def _svg_avatar_data_uri(
    text: str,
    background: str = "#4c566a",
    foreground: str = "#ffffff",
) -> str:
    label = (text or "?")[0]
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='64' height='64' viewBox='0 0 64 64'>"
        f"<rect width='64' height='64' rx='32' fill='{background}'/>"
        f"<text x='32' y='32' dominant-baseline='middle' text-anchor='middle' "
        f"font-size='28' font-family='Arial, sans-serif' fill='{foreground}'>{label}</text>"
        "</svg>"
    )
    return f"data:image/svg+xml;utf8,{quote(svg)}"


@lru_cache(maxsize=32)
def _image_data_uri(image_path: str) -> str:
    suffix = Path(image_path).suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix == "jpg" else suffix
    payload = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{payload}"


def get_chat_avatar(role_id: str) -> str:
    """Return an avatar usable by st.chat_message."""
    return get_avatar_path(role_id) or _svg_avatar_data_uri(
        avatar_text(role_id),
        background=ROLE_COLORS.get(role_id, "#4c566a"),
    )


def get_user_avatar() -> str:
    return get_chat_avatar("user")


def get_html_avatar_uri(role_id: str) -> str:
    image_path = get_avatar_path(role_id)
    if image_path:
        return _image_data_uri(image_path)
    return _svg_avatar_data_uri(
        avatar_text(role_id),
        background=ROLE_COLORS.get(role_id, "#4c566a"),
    )


def avatar_html(role_id: str) -> str:
    css_class = avatar_class(role_id)
    avatar_uri = get_html_avatar_uri(role_id)
    return (
        f'<span class="avatar avatar-image {css_class}" '
        f'style="background-image:url(\'{avatar_uri}\');"></span>'
    )


def get_banner_uri(role_id: str) -> str:
    banner_path = BANNER_DIR / f"{role_id}_banner.jpg"
    if banner_path.is_file():
        return _image_data_uri(str(banner_path))
    return ""
