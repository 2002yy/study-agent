"""Cheap candidate ranking. Discovery quality never authorizes evidence."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.web.tool_evidence import _public_url
from src.web.recovery_candidates import canonical_document


def scoped_domain(query: str) -> str:
    match = re.fullmatch(r"site:([A-Za-z0-9.-]+)\s+[^()]+", query)
    if not match or re.search(r"(?:\bOR\b|-site:|\bsite:)", query[match.end(1):]):
        return ""
    return match.group(1).lower().rstrip(".")


def in_scope(url: str, domain: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return not domain or host == domain or host.endswith("." + domain)


def url_identity(url: str) -> str:
    parsed = urlparse(url)
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parsed.query)
                             if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid"}))
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", query, ""))


def candidate_score(item: dict[str, Any], query: str) -> float:
    text = " ".join(str(item.get(k) or "") for k in ("title", "snippet", "url")).casefold()
    focused = re.sub(r"site:\S+", "", query).strip().casefold()
    tokens = set(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]", focused))
    found = set(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]", text))
    score = len(tokens & found) / max(1, len(tokens))
    versions = re.findall(r"\d+(?:\.\d+)+", focused)
    if versions and not all(version in text for version in versions):
        score *= .3
    # Homepages rarely answer a specific question, even when their title shares
    # the product name. A one-word entity lookup can still use the homepage.
    if len(tokens) > 1 and urlparse(str(item.get("url", ""))).path.strip("/") in {"", "en", "zh"}:
        score *= .4
    return score


def rank_candidates(items: list[dict[str, Any]], query: str, limit: int) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    domain = scoped_domain(query)
    for item in items:
        url = _public_url(item.get("url"))
        if not url or not in_scope(url, domain):
            continue
        key = url_identity(url)
        providers = list(item.get("providers") or [])
        if key in merged:
            previous = merged[key]
            previous["providers"] = list(dict.fromkeys([*previous.get("providers", []), *providers]))
            if len(str(item.get("snippet", ""))) > len(str(previous.get("snippet", ""))):
                previous["snippet"] = item["snippet"]
        else:
            merged[key] = {**item, "providers": providers}
    ranked = sorted(merged.values(), key=lambda row: -candidate_score(row, query))
    # Round-robin hosts inside equal relevance groups; a mirror farm cannot
    # monopolize the retained pool merely by returning more URLs.
    counts: dict[str, int] = {}
    decorated = []
    for index, row in enumerate(ranked):
        host = (urlparse(row["url"]).hostname or "").lower()
        ordinal = counts.get(host, 0)
        counts[host] = ordinal + 1
        decorated.append(((-round(candidate_score(row, query), 1), ordinal, index), row))
    return [row for _, row in sorted(decorated, key=lambda value: value[0])][:limit]


def discovery_sufficient(items: list[dict[str, Any]], query: str, limit: int) -> bool:
    good = [item for item in rank_candidates(items, query, limit) if candidate_score(item, query) >= .65]
    hosts = {(urlparse(item["url"]).hostname or "").lower() for item in good}
    documents = {canonical_document(item["url"]) for item in good}
    # A scoped official query can intentionally return one source family.
    return len(documents) >= min(3, limit) and (bool(scoped_domain(query)) or len(hosts) >= 2)
