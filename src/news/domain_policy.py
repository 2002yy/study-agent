"""Domain policy helpers for the web/news agent pipeline.

The policy is intentionally conservative:

- soft mode prefers trusted/technical domains but keeps unknown domains;
- hard-blocked login/account/auth pages are skipped for article fetching;
- no paid API or external reader dependency is introduced here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse


TECH_QUERY_TERMS = {
    "api",
    "sdk",
    "github",
    "git",
    "python",
    "java",
    "javascript",
    "typescript",
    "rust",
    "golang",
    "go",
    "c++",
    "cpp",
    "c#",
    "react",
    "vue",
    "nextjs",
    "node",
    "godot",
    "pytorch",
    "tensorflow",
    "openai",
    "llm",
    "agent",
    "bug",
    "error",
    "traceback",
    "exception",
    "文档",
    "代码",
    "编程",
    "接口",
    "模型",
    "报错",
    "调试",
}

PREFER_TECH_DOMAINS = (
    "github.com",
    "stackoverflow.com",
    "docs.python.org",
    "pytorch.org",
    "tensorflow.org",
    "godotengine.org",
    "docs.godotengine.org",
    "readthedocs.io",
    "developer.mozilla.org",
    "learn.microsoft.com",
    "microsoft.com",
    "openai.com",
    "platform.openai.com",
    "arxiv.org",
    "huggingface.co",
)

PREFER_GENERAL_SOURCE_DOMAINS = (
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "theguardian.com",
    "nytimes.com",
    "wsj.com",
    "caixin.com",
    "yicai.com",
    "sina.com.cn",
)

TRUSTED_TECH_COMMUNITY_DOMAINS = (
    "medium.com",
    "dev.to",
    "infoq.cn",
    "infoq.com",
    "51cto.com",
    "csdn.net",
)

HARD_BLOCK_HOST_PREFIXES = (
    "login.",
    "account.",
    "accounts.",
    "auth.",
    "oauth.",
    "passport.",
)

HARD_BLOCK_PATH_PATTERNS = (
    "/login",
    "/signin",
    "/sign-in",
    "/signup",
    "/sign-up",
    "/account",
    "/accounts",
    "/oauth",
    "/authorize",
    "/auth/",
    "/session",
)

SOFT_PENALTY_PATH_PATTERNS = (
    "/tag/",
    "/tags/",
    "/search",
    "/category/",
    "/topics/",
)


@dataclass(frozen=True)
class DomainPolicyDecision:
    """Policy result attached to a news item."""

    domain: str
    intent: str
    score: int = 0
    blocked: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _normalize_domain(domain: str) -> str:
    return (domain or "").strip().lower().removeprefix("www.")


def _domain_matches(domain: str, candidate: str) -> bool:
    domain = _normalize_domain(domain)
    candidate = _normalize_domain(candidate)
    return bool(domain and candidate and (domain == candidate or domain.endswith(f".{candidate}")))


def _item_url(item: dict) -> str:
    return (
        item.get("resolved_link")
        or item.get("canonical_url")
        or item.get("link")
        or ""
    ).strip()


def item_domain(item: dict) -> str:
    domain = _normalize_domain(item.get("domain", ""))
    if domain:
        return domain
    try:
        parsed = urlparse(_item_url(item))
    except Exception:
        return ""
    return _normalize_domain(parsed.hostname or "")


def infer_query_intent(query_text: str) -> str:
    lowered = (query_text or "").strip().lower()
    if not lowered:
        return "general"

    tokens = set(re.findall(r"[a-z0-9+#._-]+|[一-鿿]{2,}", lowered))
    if tokens & TECH_QUERY_TERMS:
        return "tech"
    return "general"


def _is_hard_blocked_url(url: str, domain: str) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    domain = _normalize_domain(domain)

    if any(domain.startswith(prefix) for prefix in HARD_BLOCK_HOST_PREFIXES):
        reasons.append("login-host")

    try:
        parsed = urlparse(url)
        path = (parsed.path or "").lower()
    except Exception:
        path = ""

    if any(pattern in path for pattern in HARD_BLOCK_PATH_PATTERNS):
        reasons.append("login-path")

    return bool(reasons), tuple(reasons)


def evaluate_domain_policy(item: dict, query_text: str = "") -> DomainPolicyDecision:
    """Return a query-aware domain decision for one news item.

    Positive score is better for search-result ranking.  Article fetching uses
    the same decision but converts it to a lower-is-better priority adjustment.
    """
    domain = item_domain(item)
    url = _item_url(item)
    intent = infer_query_intent(query_text)
    reasons: list[str] = []
    score = 0

    blocked, block_reasons = _is_hard_blocked_url(url, domain)
    reasons.extend(block_reasons)
    if blocked:
        return DomainPolicyDecision(
            domain=domain,
            intent=intent,
            score=-100,
            blocked=True,
            reasons=tuple(reasons),
        )

    if intent == "tech":
        if any(_domain_matches(domain, d) for d in PREFER_TECH_DOMAINS):
            score += 35
            reasons.append("prefer-tech-domain")
        elif any(_domain_matches(domain, d) for d in TRUSTED_TECH_COMMUNITY_DOMAINS):
            score += 12
            reasons.append("trusted-tech-community")
    else:
        if any(_domain_matches(domain, d) for d in PREFER_GENERAL_SOURCE_DOMAINS):
            score += 18
            reasons.append("prefer-general-source")

    if any(pattern in url.lower() for pattern in SOFT_PENALTY_PATH_PATTERNS):
        score -= 8
        reasons.append("soft-index-page-penalty")

    if not domain:
        score -= 12
        reasons.append("missing-domain")

    return DomainPolicyDecision(
        domain=domain,
        intent=intent,
        score=score,
        blocked=False,
        reasons=tuple(reasons),
    )


def annotate_domain_policy(item: dict, query_text: str = "") -> dict:
    """Return a copy of item with domain policy metadata attached."""
    decision = evaluate_domain_policy(item, query_text)
    annotated = dict(item)
    annotated["domain_policy"] = {
        "intent": decision.intent,
        "score": decision.score,
        "blocked": decision.blocked,
        "reasons": list(decision.reasons),
    }
    if decision.domain and not annotated.get("domain"):
        annotated["domain"] = decision.domain
    return annotated


def news_sort_score(item: dict, query_text: str = "") -> int:
    """Higher-is-better score used by news item sorting."""
    return evaluate_domain_policy(item, query_text).score


def article_priority_adjustment(item: dict, query_text: str = "") -> int:
    """Lower-is-better adjustment used by article fetch ranking."""
    decision = evaluate_domain_policy(item, query_text)
    if decision.blocked:
        return 10_000
    return -decision.score


def should_fetch_article(item: dict, query_text: str = "") -> bool:
    """Return False for hard-blocked pages that should not be fetched."""
    return not evaluate_domain_policy(item, query_text).blocked
