from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_BG = ROOT / "assets" / "backgrounds" / "chat_bg_light.jpg"


@lru_cache(maxsize=8)
def _background_data_uri(path_str: str) -> str:
    path = Path(path_str)
    if not path.is_file():
        return ""
    suffix = path.suffix.lower().lstrip(".") or "jpg"
    mime = "jpeg" if suffix == "jpg" else suffix
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{payload}"


def _build_css() -> str:
    bg_uri = _background_data_uri(str(DEFAULT_BG))
    background_block = ""
    if bg_uri:
        background_block = f"""
        .stApp {{
            background-image:
                linear-gradient(rgba(246, 245, 255, 0.50), rgba(235, 238, 255, 0.58)),
                url("{bg_uri}");
            background-size: cover;
            background-position: center top;
            background-attachment: fixed;
        }}
        [data-testid="stAppViewContainer"] {{
            background: transparent;
        }}
        [data-testid="stHeader"] {{
            background: rgba(255, 255, 255, 0.18);
        }}
        """

    return f"""
<style>
{background_block}
:root {{
    --panel-bg: rgba(255, 255, 255, 0.72);
    --panel-bg-strong: rgba(255, 255, 255, 0.88);
    --panel-bg-soft: rgba(255, 255, 255, 0.58);
    --panel-border: rgba(103, 88, 204, 0.10);
    --panel-shadow: 0 16px 48px rgba(92, 102, 166, 0.14);
    --panel-shadow-soft: 0 10px 24px rgba(92, 102, 166, 0.10);
    --text-main: #252a44;
    --text-soft: rgba(37, 42, 68, 0.72);
    --text-muted: rgba(37, 42, 68, 0.52);
    --accent: #7367f0;
    --accent-soft: #9d8dff;
    --accent-pink: #ff7eb6;
    --radius-lg: 24px;
    --radius-md: 18px;
    --radius-sm: 14px;
}}
[data-testid="stSidebar"] {{
    min-width: 17rem;
    max-width: 17rem;
    background: rgba(247, 248, 253, 0.80);
    border-right: 1px solid rgba(103, 88, 204, 0.08);
    backdrop-filter: blur(16px);
}}
[data-testid="stSidebar"] > div:first-child {{
    padding-top: 1.1rem;
}}
.block-container {{
    padding-top: 2rem;
    padding-bottom: 5rem;
    max-width: 1180px;
}}
h1 {{
    display: none;
}}
.hero-shell {{
    position: relative;
    overflow: hidden;
    padding: 0.2rem 0 0.1rem 0;
    margin-bottom: 1.2rem;
}}
.hero-backdrop {{
    position: absolute;
    inset: 0;
    background:
        radial-gradient(circle at 82% 16%, rgba(255, 255, 255, 0.34), transparent 18%),
        radial-gradient(circle at 78% 66%, rgba(173, 164, 255, 0.18), transparent 26%);
    pointer-events: none;
}}
.hero-head {{
    position: relative;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
}}
.hero-title {{
    font-size: 2.6rem;
    line-height: 1.05;
    font-weight: 800;
    color: var(--text-main);
    letter-spacing: -0.04em;
    margin-bottom: 0.4rem;
}}
.hero-wave {{
    font-size: 2.1rem;
}}
.hero-subtitle {{
    font-size: 1rem;
    line-height: 1.7;
    color: var(--text-soft);
}}
.version-badge {{
    padding: 0.55rem 0.95rem;
    border-radius: 999px;
    background: rgba(129, 116, 233, 0.16);
    border: 1px solid rgba(129, 116, 233, 0.12);
    color: #6d5ee8;
    font-size: 0.88rem;
    font-weight: 700;
}}
.status-card-grid {{
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 0.9rem;
    margin-bottom: 1rem;
}}
.status-card {{
    display: flex;
    align-items: center;
    gap: 0.85rem;
    padding: 1rem 1.05rem;
    border-radius: var(--radius-md);
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    box-shadow: var(--panel-shadow);
    backdrop-filter: blur(18px);
}}
.status-card-icon-wrap {{
    width: 2.65rem;
    height: 2.65rem;
    border-radius: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, rgba(255,255,255,0.92), rgba(121,108,243,0.10));
    border: 1px solid rgba(121,108,243,0.12);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.45);
}}
.status-card[data-accent="primary"] .status-card-icon {{
    color: #6f64f4;
}}
.status-card[data-accent="secondary"] .status-card-icon {{
    color: #8c6dff;
}}
.status-card-icon {{
    font-size: 1.25rem;
    line-height: 1;
    font-weight: 800;
}}
.status-card-label {{
    font-size: 0.82rem;
    color: var(--text-muted);
    margin-bottom: 0.18rem;
}}
.status-card-value {{
    font-size: 1rem;
    font-weight: 700;
    color: var(--text-main);
}}
.focus-panel {{
    position: relative;
    overflow: hidden;
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    padding: 1.15rem 1.25rem;
    border-radius: var(--radius-lg);
    background: var(--panel-bg-strong);
    border: 1px solid var(--panel-border);
    box-shadow: var(--panel-shadow);
    backdrop-filter: blur(18px);
}}
.focus-panel-content {{
    flex: 1;
}}
.focus-panel-title {{
    font-size: 1.05rem;
    font-weight: 800;
    color: var(--text-main);
    margin-bottom: 0.7rem;
}}
.focus-panel-copy {{
    font-size: 0.98rem;
    line-height: 1.72;
    color: var(--text-soft);
    margin-bottom: 0.8rem;
}}
.focus-panel-tags {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.55rem;
}}
.focus-panel-tags.compact {{
    margin-top: 0.85rem;
}}
.focus-tag {{
    padding: 0.42rem 0.8rem;
    border-radius: 999px;
    background: rgba(129, 116, 233, 0.12);
    color: #6c5fe9;
    font-size: 0.82rem;
    font-weight: 700;
}}
.focus-panel-visual {{
    position: relative;
    flex: 0 0 12rem;
    min-height: 10rem;
    display: flex;
    align-items: center;
    justify-content: center;
}}
.focus-panel-aura {{
    position: absolute;
    inset: 0.4rem 1.1rem;
    border-radius: 24px;
    background-size: cover;
    background-position: center;
    opacity: 0.20;
    filter: blur(6px) saturate(1.08);
}}
.focus-panel-avatar {{
    position: relative;
    width: 7.6rem;
    height: 7.6rem;
    border-radius: 28px;
    background-size: cover;
    background-position: center;
    box-shadow: 0 16px 40px rgba(85, 76, 159, 0.26);
    border: 1px solid rgba(255, 255, 255, 0.48);
}}
.focus-panel-ring {{
    position: absolute;
    right: 0.3rem;
    top: 0.1rem;
    width: 3rem;
    height: 3rem;
    border-radius: 999px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.4rem;
    color: #8c6dff;
    background: rgba(255, 255, 255, 0.84);
    border: 1px solid rgba(129, 116, 233, 0.14);
    box-shadow: var(--panel-shadow-soft);
}}
.wechat-compact-grid {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.75rem;
    margin-top: 0.9rem;
}}
.wechat-compact-item {{
    display: flex;
    flex-direction: column;
    gap: 0.18rem;
    padding: 0.75rem 0.85rem;
    border-radius: 16px;
    background: rgba(248, 247, 255, 0.76);
    border: 1px solid rgba(129, 116, 233, 0.08);
}}
.wechat-compact-label {{
    font-size: 0.76rem;
    color: var(--text-muted);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    font-weight: 700;
}}
.wechat-compact-value {{
    font-size: 0.96rem;
    color: var(--text-main);
    font-weight: 800;
}}
.welcome-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    margin-bottom: 1rem;
}}
.welcome-card,
.resume-card,
.welcome-summary-card {{
    padding: 1.3rem;
    border-radius: var(--radius-lg);
    background: var(--panel-bg-strong);
    border: 1px solid var(--panel-border);
    box-shadow: var(--panel-shadow);
    backdrop-filter: blur(18px);
}}
.welcome-title,
.resume-title {{
    font-size: 1.12rem;
    font-weight: 800;
    color: var(--text-main);
    margin-bottom: 0.45rem;
}}
.resume-head {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 0.65rem;
}}
.resume-portrait {{
    width: 4.8rem;
    height: 4.8rem;
    border-radius: 20px;
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
    box-shadow: 0 12px 30px rgba(98, 91, 176, 0.18);
    border: 1px solid rgba(255, 255, 255, 0.55);
}}
.welcome-copy,
.resume-copy,
.welcome-focus-copy {{
    font-size: 0.95rem;
    line-height: 1.72;
    color: var(--text-soft);
}}
.welcome-copy {{
    margin-bottom: 0.8rem;
}}
.welcome-focus {{
    margin-bottom: 0.9rem;
    padding: 0.95rem 1rem;
    border-radius: var(--radius-md);
    background: rgba(248, 247, 255, 0.82);
    border: 1px solid rgba(129, 116, 233, 0.08);
}}
.welcome-focus-label,
.welcome-list-label,
.resume-list-title {{
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    margin-bottom: 0.42rem;
    font-weight: 700;
}}
.quick-entry-arrow {{
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 2.75rem;
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.72);
    border: 1px solid rgba(129, 116, 233, 0.10);
    color: #8170eb;
    font-size: 1.4rem;
    box-shadow: var(--panel-shadow-soft);
}}
.input-dock-meta {{
    margin-top: 1rem;
    margin-bottom: 0;
    padding: 1rem 1.1rem 0.82rem 1.1rem;
    border-radius: 22px 22px 0 0;
    background: rgba(255, 255, 255, 0.80);
    border: 1px solid var(--panel-border);
    border-bottom: none;
    box-shadow: var(--panel-shadow);
    backdrop-filter: blur(18px);
}}
.input-dock-top {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    margin-bottom: 0.7rem;
}}
.input-dock-title {{
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--text-muted);
    font-weight: 700;
}}
.input-dock-summary {{
    font-size: 0.94rem;
    color: var(--text-main);
    font-weight: 700;
}}
.input-dock-pill {{
    padding: 0.42rem 0.8rem;
    border-radius: 999px;
    background: linear-gradient(135deg, rgba(124,111,241,0.14), rgba(255,126,182,0.14));
    color: #6658e9;
    font-size: 0.82rem;
    font-weight: 700;
}}
.input-dock-chips {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
}}
.input-dock-chip {{
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.38rem 0.72rem;
    border-radius: 999px;
    background: rgba(129, 116, 233, 0.10);
    border: 1px solid rgba(129, 116, 233, 0.08);
    color: var(--text-main);
    font-size: 0.82rem;
    font-weight: 700;
}}
.input-dock-chip-label {{
    color: var(--text-muted);
    font-weight: 600;
}}
[data-testid="stChatMessage"] {{
    background: rgba(255, 255, 255, 0.82);
    border: 1px solid var(--panel-border);
    border-radius: 20px;
    padding: 0.9rem 1rem;
    margin-bottom: 0.8rem;
    box-shadow: 0 12px 34px rgba(92, 102, 166, 0.10);
    backdrop-filter: blur(16px);
}}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p,
[data-testid="stChatMessage"] li {{
    line-height: 1.74;
    color: var(--text-main);
}}
[data-testid="stChatMessage"] pre,
[data-testid="stChatMessage"] code {{
    background: rgba(21, 27, 43, 0.96) !important;
}}
[data-testid="stChatMessage"] table {{
    background: rgba(255, 255, 255, 0.86);
}}
[data-testid="stChatInput"] {{
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid var(--panel-border);
    border-radius: 0 0 22px 22px;
    border-top: none;
    box-shadow: var(--panel-shadow);
    backdrop-filter: blur(18px);
    padding: 0.52rem 0.72rem 0.58rem 0.72rem;
}}
[data-testid="stChatInput"] textarea {{
    font-size: 1rem !important;
    color: var(--text-main) !important;
}}
[data-testid="stChatInput"] button {{
    border-radius: 999px !important;
    width: 2.75rem !important;
    height: 2.75rem !important;
    background: linear-gradient(135deg, #7a6cf2, #6a8dff) !important;
    color: #fff !important;
    box-shadow: 0 12px 30px rgba(97, 107, 214, 0.26);
}}
.sidebar-section-title {{
    font-size: 1.05rem;
    font-weight: 800;
    color: var(--text-main);
    margin: 0.2rem 0 0.7rem 0;
}}
.sidebar-mini-card {{
    padding: 0.72rem 0.82rem;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.48);
    border: 1px solid rgba(129, 116, 233, 0.08);
    margin-bottom: 0.55rem;
}}
.sidebar-mini-label {{
    font-size: 0.78rem;
    color: var(--text-muted);
    margin-bottom: 0.18rem;
}}
.sidebar-mini-value {{
    font-size: 0.92rem;
    line-height: 1.45;
    color: var(--text-main);
    font-weight: 700;
}}
.sidebar-divider {{
    height: 1px;
    background: rgba(103, 88, 204, 0.10);
    margin: 1.15rem 0;
}}
.stButton > button, .stDownloadButton > button {{
    border-radius: var(--radius-sm);
    border: 1px solid rgba(129, 116, 233, 0.10);
    background: rgba(255, 255, 255, 0.82);
    box-shadow: var(--panel-shadow-soft);
}}
.stButton > button[kind="secondary"] {{
    background: rgba(255, 255, 255, 0.78);
}}
.wechat-msg {{
    margin: 0.5rem 0;
    display: flex;
    flex-direction: column;
}}
.wechat-msg.left {{
    align-items: flex-start;
}}
.wechat-msg.right {{
    align-items: flex-end;
}}
.wechat-msg .sender {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.2rem;
}}
.wechat-msg.right .sender {{
    justify-content: flex-end;
}}
.wechat-msg .sender .name {{
    font-weight: 600;
    font-size: 0.9rem;
    cursor: pointer;
}}
.wechat-msg .sender .avatar {{
    width: 34px;
    height: 34px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.78rem;
    font-weight: 700;
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
    overflow: hidden;
}}
.wechat-msg .bubble {{
    padding: 0.55rem 0.82rem;
    display: inline-block;
    max-width: 85%;
    border-radius: 14px;
    background: rgba(32, 37, 59, 0.92);
    color: #f3f5ff;
    overflow-wrap: break-word;
    word-break: break-word;
    backdrop-filter: blur(8px);
}}
.wechat-msg.right .bubble {{
    background: rgba(120, 108, 242, 0.92);
    color: #ffffff;
    border-right: 3px solid rgba(255, 255, 255, 0.40);
}}
.wechat-msg .bubble code,
.wechat-msg .bubble pre {{
    white-space: pre-wrap;
    overflow-x: auto;
    background: #111;
    padding: 0.2rem 0.4rem;
    border-radius: 4px;
}}
.wechat-msg .bubble table {{
    font-size: 0.85rem;
}}
.wechat-msg.m7 .name {{ color: #f38ba8; }}
.wechat-msg.m7 .avatar {{ background-color: #f38ba8; color: #1e1e2e; }}
.wechat-msg.m7 .bubble {{ border-left: 3px solid #f38ba8; }}
.wechat-msg.kq .name {{ color: #cba6f7; }}
.wechat-msg.kq .avatar {{ background-color: #cba6f7; color: #1e1e2e; }}
.wechat-msg.kq .bubble {{ border-left: 3px solid #cba6f7; }}
.wechat-msg.nh .name {{ color: #94e2d5; }}
.wechat-msg.nh .avatar {{ background-color: #94e2d5; color: #1e1e2e; }}
.wechat-msg.nh .bubble {{ border-left: 3px solid #94e2d5; }}
.wechat-msg.ly .name {{ color: #fab387; }}
.wechat-msg.ly .avatar {{ background-color: #fab387; color: #1e1e2e; }}
.wechat-msg.ly .bubble {{ border-left: 3px solid #fab387; }}
.wechat-msg.user .name {{ color: #d7ddff; }}
.wechat-msg.user .avatar {{ background-color: #7a6cf2; color: #ffffff; }}
.wechat-msg.system {{
    justify-content: center;
}}
.wechat-msg .bubble.system-bubble {{
    max-width: 92%;
    background: rgba(255, 255, 255, 0.14);
    color: #e3e7ff;
    border: 1px dashed rgba(215, 221, 255, 0.26);
    text-align: left;
}}
.wechat-card {{
    border: 1px solid rgba(103, 88, 204, 0.10);
    border-radius: 20px;
    padding: 1rem;
    background: rgba(32, 37, 59, 0.82);
    margin: 1rem 0;
    box-shadow: 0 14px 34px rgba(46, 51, 88, 0.14);
    backdrop-filter: blur(14px);
}}
.wechat-card .group-name {{
    font-size: 1.1rem;
    font-weight: 700;
    color: #f3f5ff;
}}
.wechat-opening-card {{
    padding: 1.25rem 1.3rem;
    margin: 0.25rem 0 1rem 0;
    border-radius: var(--radius-lg);
    background: var(--panel-bg-strong);
    border: 1px solid var(--panel-border);
    box-shadow: var(--panel-shadow);
    backdrop-filter: blur(18px);
}}
.wechat-opening-title {{
    font-size: 1.08rem;
    font-weight: 800;
    color: var(--text-main);
    margin-bottom: 0.45rem;
}}
.wechat-opening-desc {{
    font-size: 0.95rem;
    line-height: 1.72;
    color: var(--text-soft);
}}
.wechat-card .time-divider {{
    text-align: center;
    color: #a7aed4;
    font-size: 0.78rem;
    margin: 1rem 0;
}}
.wechat-card .time-divider::before {{ content: "—— "; }}
.wechat-card .time-divider::after {{ content: " ——"; }}
.wechat-cite-row {{
    padding: 0.8rem 0.95rem;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.36);
    border: 1px solid rgba(129, 116, 233, 0.10);
    margin-bottom: 0.7rem;
}}
.wechat-cite-row.added {{
    background: rgba(226, 247, 235, 0.62);
    border-color: rgba(42, 176, 105, 0.16);
}}
.wechat-cite-card {{
    padding: 0.8rem 0.95rem;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.36);
    border: 1px solid rgba(129, 116, 233, 0.10);
    margin-bottom: 0.45rem;
    min-height: 7.4rem;
}}
.wechat-cite-card.added {{
    background: rgba(226, 247, 235, 0.62);
    border-color: rgba(42, 176, 105, 0.16);
}}
.wechat-cite-head {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.6rem;
    margin-bottom: 0.35rem;
}}
.wechat-cite-meta {{
    font-size: 0.82rem;
    font-weight: 700;
    color: rgba(67, 76, 128, 0.78);
}}
.wechat-cite-text {{
    font-size: 0.94rem;
    line-height: 1.62;
    color: var(--text-main);
}}
.wechat-cite-status {{
    margin-top: 0.45rem;
}}
.wechat-cite-badge {{
    display: inline-flex;
    align-items: center;
    padding: 0.24rem 0.62rem;
    border-radius: 999px;
    background: rgba(129, 116, 233, 0.12);
    color: #6b5fe6;
    font-size: 0.76rem;
    font-weight: 700;
}}
.wechat-cite-badge.added {{
    background: rgba(42, 176, 105, 0.14);
    color: #1d9b5f;
}}
.unread-badge {{
    background: #f38ba8;
    color: #1e1e2e;
    border-radius: 10px;
    padding: 0rem 0.4rem;
    font-size: 0.72rem;
    font-weight: 700;
    margin-left: 0.3rem;
    display: inline-block;
}}
@media (max-width: 1080px) {{
    .status-card-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .welcome-grid {{
        grid-template-columns: 1fr;
    }}
    .focus-panel {{
        flex-direction: column;
    }}
    .focus-panel-visual {{
        min-height: 8rem;
    }}
}}
@media (max-width: 960px) {{
    [data-testid="stSidebar"] {{
        min-width: auto;
        max-width: none;
    }}
    .block-container {{
        max-width: 100%;
        padding-left: 1rem;
        padding-right: 1rem;
    }}
    .hero-head,
    .input-dock-top {{
        flex-direction: column;
        align-items: flex-start;
    }}
    .status-card-grid {{
        grid-template-columns: 1fr;
    }}
}}
</style>
"""


def inject_theme():
    st.markdown(_build_css(), unsafe_allow_html=True)
