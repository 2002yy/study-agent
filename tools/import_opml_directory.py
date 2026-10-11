"""Offline OPML source-directory importer (B-Search-2B7-A).

Parses a bounded OPML snapshot, normalizes/dedupes feed URLs, merges per-category
and language tags, assigns stable source_ids, and writes a local index. NO network:
import and recall never contact a feed; every source starts ``cataloged``.

Usage:
  python tools/import_opml_directory.py --snapshot <dir> --out <index.json>
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree as ET

MAX_OPML_FILES = 64
MAX_OUTLINES = 20000


def _normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        return ""
    if parts.username or parts.password:  # reject credentials in URL
        return ""
    if parts.port not in (None, 80, 443):  # reject abnormal ports
        return ""
    try:  # reject IP-literal sources that are not global
        if not ipaddress.ip_address(host).is_global:
            return ""
    except ValueError:
        pass
    port = "" if parts.port in (None, 80, 443) else f":{parts.port}"
    path = parts.path or ""
    return urlunsplit((scheme, host + port, path, parts.query, ""))


def _stable_id(url: str) -> str:
    return "feed-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _parse_opml(path: Path, category: str, language: str) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    if "<!ENTITY" in text:  # reject entity-expansion vectors
        raise ValueError("opml_entity_rejected")
    # Some OPML feeds contain raw '&' in URLs/titles; escape only bare ampersands.
    text = re.sub(r"&(?!(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*);)", "&amp;", text)
    root = ET.fromstring(text)
    rows: list[dict[str, str]] = []
    for outline in root.iter("outline"):
        xml_url = outline.get("xmlUrl") or ""
        normalized = _normalize_url(xml_url)
        if not normalized:
            continue
        rows.append({
            "title": (outline.get("title") or outline.get("text") or "").strip(),
            "xml_url": normalized,
            "html_url": _normalize_url(outline.get("htmlUrl") or ""),
            "category": category,
            "language": language,
        })
        if len(rows) >= MAX_OUTLINES:
            raise ValueError("opml_too_many_outlines")
    return rows


def build_index(snapshot: Path, upstream_commit: str = "") -> dict:
    feeds_dir = snapshot / "feeds"
    files = sorted(feeds_dir.glob("*.opml"))[:MAX_OPML_FILES]
    if not files:
        raise ValueError("no_category_opml")
    sources: dict[str, dict] = {}
    raw = invalid = 0
    for path in files:
        match = re.match(r"^(cn|en)-(.+)\.opml$", path.name)
        if not match:
            invalid += 1
            continue
        language, category = match.group(1), match.group(2)
        try:
            rows = _parse_opml(path, category, language)
        except (ValueError, ET.ParseError):
            invalid += 1
            continue
        for row in rows:
            raw += 1
            url = row["xml_url"]
            entry = sources.setdefault(url, {
                "source_id": _stable_id(url), "xml_url": url, "title": row["title"],
                "html_url": row["html_url"], "categories": [], "languages": [],
                "status": "cataloged",
                "provenance": {"repo": "xiangyugongzuoliu/awesome-rss-feeds-list"},
            })
            if row["category"] not in entry["categories"]:
                entry["categories"].append(row["category"])
            if row["language"] not in entry["languages"]:
                entry["languages"].append(row["language"])
            if not entry["title"]:
                entry["title"] = row["title"]
    stats_path = snapshot / "stats.json"
    upstream_stats = json.loads(stats_path.read_text(encoding="utf-8").lstrip("\ufeff")) if stats_path.exists() else {}
    license_path = snapshot / "LICENSE"
    file_hashes = {}
    for path in [snapshot / "feeds.opml", stats_path, *files]:
        if path.exists():
            file_hashes[str(path.relative_to(snapshot)).replace("\\", "/")] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "schema_version": "source-directory-v1",
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "upstream": {
            "repo": "xiangyugongzuoliu/awesome-rss-feeds-list",
            "commit": upstream_commit,
            "stats": upstream_stats,
            "license": (license_path.read_text(encoding="utf-8", errors="replace")[:200] if license_path.exists() else ""),
            "feeds_opml_sha256": hashlib.sha256((snapshot / "feeds.opml").read_bytes()).hexdigest() if (snapshot / "feeds.opml").exists() else "",
            "file_hashes": file_hashes,
        },
        "sources": sorted(sources.values(), key=lambda s: s["source_id"]),
        "stats": {
            "raw_outlines": raw,
            "invalid_files": invalid,
            "final_sources": len(sources),
            "upstream_active_count": upstream_stats.get("active_count"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--upstream-commit", default="")
    args = parser.parse_args()
    index = build_index(Path(args.snapshot), args.upstream_commit)
    Path(args.out).write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(index["stats"], ensure_ascii=False))


if __name__ == "__main__":
    main()
