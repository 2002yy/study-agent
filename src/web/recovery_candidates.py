"""Run-local diversity and duplicate suppression; no global host reputation."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlparse

_LANGUAGES = {"en", "zh", "ja", "ko", "fr", "de", "es", "pt", "it", "ru", "ar"}
_TRACKING = {"gclid", "fbclid", "ref"}
_BLOCKED_PATHS = {"app-unavailable-in-region", "login", "signin", "sign-in"}


def canonical_document(url: str) -> str:
    parsed = urlparse(url)
    parts = unquote(parsed.path).strip("/").split("/")
    # These are scheduling families only. Never rewrite a fetched URL or use
    # this identity to authorize citations across locale/redirect boundaries.
    parts = [
        part
        for i, part in enumerate(parts)
        if not (
            i < 3
            and (
                part.lower() in _LANGUAGES
                or (
                    "-" in part
                    and part.split("-", 1)[0].lower() in _LANGUAGES
                    and len(part.split("-", 1)[1]) == 2
                )
            )
        )
    ]
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parsed.query)
            if not k.lower().startswith("utm_") and k.lower() not in _TRACKING
        )
    )
    try:
        port = parsed.port or ""
    except ValueError:
        port = "invalid"
    return f"{(parsed.hostname or '').lower()}:{port}/{'/'.join(parts)}?{query}"


def source_family(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


class CandidateScheduler:
    def __init__(self) -> None:
        self.urls: set[str] = set()
        self.documents: set[str] = set()
        self.redirect_targets: set[str] = set()
        self.families: set[str] = set()
        self.host_state: dict[str, dict[str, Any]] = {}

    def rejection(self, url: str) -> str:
        if url in self.urls:
            return "already_attempted_url"
        if canonical_document(url) in self.documents:
            return "same_document_locale_variant"
        if canonical_document(url) in self.redirect_targets:
            return "already_read_redirect_target"
        if self.host_state.get(source_family(url), {}).get("cooldown"):
            return "run_local_host_cooldown"
        return ""

    def order(
        self, candidates: list[dict[str, Any]], domains: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        ranked = []
        # Preserve the assessor's relevance order inside equal priority groups.
        for index, record in enumerate(candidates):
            assessment = record["assessment"]
            host = source_family(assessment["url"])
            failed = int(self.host_state.get(host, {}).get("failures", 0))
            ranked.append(
                (
                    (
                        bool(failed),
                        host not in domains,
                        host in seen or host in self.families,
                        -float(assessment.get("relevance", 0)),
                        index,
                    ),
                    record,
                )
            )
            seen.add(host)
        return [record for _, record in sorted(ranked, key=lambda value: value[0])]

    def begin(self, url: str) -> None:
        self.urls.add(url)
        self.documents.add(canonical_document(url))
        self.families.add(source_family(url))

    def finish(self, url: str, result: dict[str, Any]) -> str:
        final_url = str(result.get("url") or url)
        if final_url != url:
            self.redirect_targets.add(canonical_document(final_url))
        path = urlparse(final_url).path.strip("/").lower()
        blocked = path in _BLOCKED_PATHS
        if (
            blocked
            or not (result.get("ok") is True or result.get("ok") == "true")
            or result.get("error")
        ):
            host = source_family(url)
            previous = self.host_state.get(host, {})
            failures = int(previous.get("failures", 0)) + 1
            reason = (
                "REGION_UNAVAILABLE"
                if path == "app-unavailable-in-region"
                else (
                    "ACCESS_WALL"
                    if blocked
                    else str(
                        result.get("error_code") or result.get("error") or "read_failed"
                    )[:200]
                )
            )
            self.host_state[host] = {
                "failures": failures,
                "reason": reason,
                "cooldown": blocked or failures >= 2,
            }
            return reason
        return ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "unique_canonical_docs": len(self.documents),
            "unique_source_families": len(self.families),
            "redirect_targets": len(self.redirect_targets),
            "host_state": {
                host: dict(state) for host, state in self.host_state.items()
            },
        }
