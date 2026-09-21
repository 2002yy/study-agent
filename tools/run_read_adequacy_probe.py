"""§46 read adequacy characterization: short official pages, shapes, and
whether a richer LOCAL extraction exists for the same URL.

Three questions per URL, all within the existing dependency boundary (no new
service, no r.jina.ai):

1. How short is the production read? (``ActiveResearchGateway.read`` chars)
2. What shape is a short page? (js_shell / anti_bot / redirect_landing /
   extraction_loss / short_doc)
3. Does the same fetched HTML yield more text through another LOCAL extractor?
   The production chain is trafilatura(precision) -> readability ->
   fallback_parser and returns on the first non-empty result, so a short
   trafilatura snippet can mask a much longer readability/fallback text.

Only if question 3 holds is a local reader (extractor) fallback worth
designing. Diagnostic-only; no production path changes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from tools.run_recall_target_audit import TARGETS  # noqa: E402

SCHEMA_VERSION = "read-adequacy-probe-v1"
RICHER_FACTOR = 3.0

# §71C-3a: the production adequacy gate owns these; the probe measures with the
# exact same values so measurement and escalation cannot drift.
from src.web.research.read_adequacy import (  # noqa: E402
    ANTI_BOT_MARKERS,
    JS_SHELL_MARKERS,
    SHORT_CHAR_THRESHOLD,
)


def classify_read(
    *,
    production_chars: int,
    html_chars: int,
    best_local_chars: int,
    text: str,
    final_url: str,
    requested_url: str,
) -> str:
    """Mechanical shape for the §46 characterization."""

    lowered = str(text or "").lower()
    if any(marker in lowered for marker in ANTI_BOT_MARKERS):
        return "anti_bot_or_error"
    if production_chars >= SHORT_CHAR_THRESHOLD:
        return "ok"
    if any(marker in lowered for marker in JS_SHELL_MARKERS):
        return "js_shell"
    if final_url and _host_path(final_url) != _host_path(requested_url):
        return "redirect_landing"
    if best_local_chars >= max(SHORT_CHAR_THRESHOLD, production_chars * RICHER_FACTOR):
        return "extraction_loss"
    return "short_doc"


def _host_path(url: str) -> str:
    match = re.match(r"https?://[^/]+(/[^?#]*)?", str(url or ""))
    return (match.group(0) if match else str(url or "")).rstrip("/").lower()


@dataclass
class ReadRow:
    url: str
    source: str = "observed"
    production_ok: bool = False
    production_chars: int = 0
    production_method: str = ""
    production_error: str = ""
    html_chars: int = 0
    html_reason: str = ""
    final_url: str = ""
    content_type: str = ""
    trafilatura_chars: int = 0
    readability_chars: int = 0
    fallback_parser_chars: int = 0
    best_local_chars: int = 0
    classification: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.__dict__)
        payload["best_local_extractor"] = self.extra.get("best_local_extractor", "")
        return payload


def collect_sample_urls(
    artifacts: Sequence[Path],
    *,
    cap: int = 12,
) -> list[tuple[str, str]]:
    """Official-ish deep pages observed in artifacts + the known targets."""

    rows: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(url: str, source: str) -> None:
        key = str(url or "").rstrip("/")
        if not key or key in seen:
            return
        seen.add(key)
        rows.append((key, source))

    for target in TARGETS:
        add(target.url, "known_target")
    for path in artifacts:
        if not path.exists():
            continue
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for case in artifact.get("cases") or []:
            if not isinstance(case, Mapping):
                continue
            for source_row in case.get("sources") or []:
                if not isinstance(source_row, Mapping):
                    continue
                url = str(source_row.get("url") or "")
                if _looks_like_deep_official(url):
                    add(url, "observed")
    return rows[:cap]


def _looks_like_deep_official(url: str) -> bool:
    match = re.match(r"https?://([^/]+)(/[^?#]*)?", str(url or ""))
    if not match:
        return False
    host = match.group(1).lower()
    path = (match.group(2) or "").strip("/")
    if not path:
        return False
    official_markers = (
        "docs.",
        "developer.",
        "support.",
        ".org",
        ".gov",
        "github.com",
    )
    return any(marker in host for marker in official_markers)


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    short = [row for row in rows if int(row.get("production_chars") or 0) < SHORT_CHAR_THRESHOLD]
    shapes: dict[str, int] = {}
    for row in rows:
        shape = str(row.get("classification") or "unknown")
        shapes[shape] = shapes.get(shape, 0) + 1
    extraction_loss = shapes.get("extraction_loss", 0)
    return {
        "urls": total,
        "short_pages": len(short),
        "short_ratio": round(len(short) / total, 3) if total else None,
        "shape_counts": dict(sorted(shapes.items())),
        "local_richer_available": extraction_loss,
        "answer_question_3": (
            "yes: at least one short page yields much more text through another "
            "local extractor"
            if extraction_loss
            else "no: no short page could be improved by another local extractor"
        ),
    }


def probe_url(
    url: str,
    *,
    production_reader: Callable[[str], Mapping[str, Any]],
    html_fetcher: Callable[[str], tuple[str, str, str, str]],
    extractors: Sequence[tuple[str, Callable[[str], str]]],
) -> dict[str, Any]:
    row = ReadRow(url=url)
    raw = production_reader(url) or {}
    row.production_ok = raw.get("ok") is True
    row.production_chars = len(str(raw.get("content") or ""))
    row.production_method = str(raw.get("method") or "")
    row.production_error = str(raw.get("error") or "")
    try:
        html, final_url, content_type, reason = html_fetcher(url)
    except Exception as exc:  # transient network resets must stay visible
        html, final_url, content_type = "", "", ""
        reason = f"exception:{type(exc).__name__}:{str(exc)[:80]}"
    row.html_chars = len(html or "")
    row.html_reason = reason
    row.final_url = final_url or ""
    row.content_type = content_type or ""
    best_name = ""
    best_chars = 0
    if html:
        for name, extractor in extractors:
            chars = len(extractor(html) or "")
            setattr(row, f"{name}_chars", chars)
            if chars > best_chars:
                best_chars = chars
                best_name = name
    row.best_local_chars = max(best_chars, row.production_chars)
    row.extra["best_local_extractor"] = best_name
    row.classification = classify_read(
        production_chars=row.production_chars,
        html_chars=row.html_chars,
        best_local_chars=row.best_local_chars,
        text=str(raw.get("content") or ""),
        final_url=row.final_url,
        requested_url=url,
    )
    if (
        row.classification == "short_doc"
        and row.html_chars == 0
        and row.html_reason
        and not row.production_ok
    ):
        # The page never arrived at all (network resets etc.): not a shape.
        row.classification = "fetch_failed"
    return row.to_dict()


def _live_components() -> tuple[
    Callable[[str], Mapping[str, Any]],
    Callable[[str], tuple[str, str, str, str]],
    list[tuple[str, Callable[[str], str]]],
]:
    from src.news.article_extractor import (
        extract_article_text_with_fallback_parser,
        extract_article_text_with_readability,
        extract_article_text_with_trafilatura,
    )
    from src.news.article_fetcher import _fetch_html_payload
    from src.web.research.active_adapter import ActiveResearchGateway

    gateway = ActiveResearchGateway()

    def production_reader(url: str) -> Mapping[str, Any]:
        return dict(gateway.read(url, max_chars=6000) or {})

    def html_fetcher(url: str) -> tuple[str, str, str, str]:
        return _fetch_html_payload(url, timeout=12, max_bytes=350_000)

    extractors = [
        (
            "trafilatura",
            lambda html: extract_article_text_with_trafilatura(html, max_chars=20000),
        ),
        (
            "readability",
            lambda html: extract_article_text_with_readability(html, max_chars=20000),
        ),
        (
            "fallback_parser",
            lambda html: extract_article_text_with_fallback_parser(html, max_chars=20000),
        ),
    ]
    return production_reader, html_fetcher, extractors


def run_probe(
    *,
    output_path: Path,
    artifacts: Sequence[Path] = (),
    urls: Sequence[str] = (),
    cap: int = 12,
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    production_reader, html_fetcher, extractors = _live_components()
    sample = [(url, "explicit") for url in urls] if urls else collect_sample_urls(
        artifacts, cap=cap
    )
    rows: list[dict[str, Any]] = []
    for url, source in sample:
        row = probe_url(
            url,
            production_reader=production_reader,
            html_fetcher=html_fetcher,
            extractors=extractors,
        )
        row["source"] = source
        rows.append(row)
        print(
            f"[{row['classification']}] prod={row['production_chars']} "
            f"html={row['html_chars']} local_best={row['best_local_chars']} "
            f"({row['extra'].get('best_local_extractor')}) :: {url[:100]}"
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "short_threshold": SHORT_CHAR_THRESHOLD,
        "sample": [{"url": url, "source": source} for url, source in sample],
        "rows": rows,
        "summary": summarize(rows),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, nargs="*", default=[])
    parser.add_argument("--urls", nargs="*", default=[])
    parser.add_argument("--cap", type=int, default=12)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    payload = run_probe(
        output_path=args.output.resolve(),
        artifacts=args.artifacts,
        urls=args.urls,
        cap=args.cap,
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
