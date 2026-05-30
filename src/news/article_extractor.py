"""Article text extraction from HTML sources."""

from __future__ import annotations

import re
from html.parser import HTMLParser


class ArticleTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip_stack: list[str] = []
        self._chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {
            "script",
            "style",
            "noscript",
            "svg",
            "canvas",
            "form",
            "nav",
            "header",
            "footer",
            "aside",
        }:
            self._skip_stack.append(tag)

        if tag in {"p", "br", "div", "section", "article", "h1", "h2", "h3", "li"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._skip_stack and self._skip_stack[-1] == tag:
            self._skip_stack.pop()

        if tag in {"p", "div", "section", "article", "li"}:
            self._chunks.append("\n")

    def handle_data(self, data):
        if self._skip_stack:
            return

        text = data.strip()
        if text:
            self._chunks.append(text)

    def get_text(self) -> str:
        raw = " ".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n\s*\n\s*\n+", "\n\n", raw)
        raw = re.sub(r"\s*\n\s*", "\n", raw)
        return raw.strip()


def clean_article_text(text: str, max_chars: int = 5000) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) < 180:
        return ""

    noise_keywords = [
        "cookie",
        "cookies",
        "subscribe",
        "sign in",
        "log in",
        "广告",
        "订阅",
        "登录",
        "注册",
        "隐私政策",
        "版权所有",
    ]

    parts = re.split(r"(?<=[。！？.!?])\s+", text)
    useful_parts = []
    for part in parts:
        lower = part.lower()
        if any(keyword in lower for keyword in noise_keywords) and len(part) < 120:
            continue
        useful_parts.append(part)

    cleaned = " ".join(useful_parts).strip()
    return cleaned[:max_chars]


def decode_html_payload(payload: bytes, content_type: str) -> str:
    match = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    encodings: list[str] = []
    if match:
        encodings.append(match.group(1))

    encodings.extend(["utf-8", "gb18030", "gbk"])

    seen: set[str] = set()
    for encoding in encodings:
        normalized = (encoding or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        try:
            decoded = payload.decode(normalized, errors="ignore")
            if decoded.strip():
                return decoded
        except Exception:
            continue

    return payload.decode("utf-8", errors="ignore")


def extract_article_text_with_trafilatura(
    html: str,
    url: str = "",
    max_chars: int = 5000,
) -> str:
    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            url=url or None,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
        return clean_article_text(text or "", max_chars=max_chars)
    except Exception:
        return ""


def extract_article_text_with_readability(
    html: str,
    max_chars: int = 5000,
) -> str:
    try:
        from readability import Document

        doc = Document(html)
        summary_html = doc.summary(html_partial=True)

        extractor = ArticleTextExtractor()
        extractor.feed(summary_html)
        text = extractor.get_text()
        return clean_article_text(text, max_chars=max_chars)
    except Exception:
        return ""


def extract_article_text_with_fallback_parser(
    html: str,
    max_chars: int = 5000,
) -> str:
    try:
        extractor = ArticleTextExtractor()
        extractor.feed(html)
        text = extractor.get_text()
        return clean_article_text(text, max_chars=max_chars)
    except Exception:
        return ""


def extract_article_text(
    html: str,
    url: str = "",
    max_chars: int = 5000,
) -> tuple[str, str]:
    text = extract_article_text_with_trafilatura(
        html,
        url=url,
        max_chars=max_chars,
    )
    if text:
        return text, "trafilatura"

    text = extract_article_text_with_readability(
        html,
        max_chars=max_chars,
    )
    if text:
        return text, "readability"

    text = extract_article_text_with_fallback_parser(
        html,
        max_chars=max_chars,
    )
    if text:
        return text, "fallback_parser"

    return "", ""


def article_method_label(method: str) -> str:
    return {
        "trafilatura": "trafilatura",
        "readability": "readability-lxml",
        "fallback_parser": "HTMLParser",
        "local_trafilatura": "本地 trafilatura",
        "local_readability": "本地 readability-lxml",
        "local_fallback_parser": "本地 HTMLParser",
        "firecrawl": "Firecrawl",
        "jina_reader": "Jina Reader",
    }.get(method, method or "未知方法")
