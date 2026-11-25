"""Render non-article payloads into bounded, structure-preserving text.

The gateway already fetches text safely; this module decides what a Markdown,
CSV, JSON or HTML-table payload should look like when a model reads it. It does
no network I/O and no evidence admission: callers keep the URL, method and
truncation marker.

Guiding rule: never turn structure into a plausible-looking lie. When a full
rendering does not fit, return an explicit structural summary instead of cutting
JSON mid-object; when a table has merged cells, skip it and say so.
"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.parse
from typing import Any

_SUFFIX_KINDS = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".csv": "csv",
    ".tsv": "tsv",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".srt": "srt",
    ".vtt": "vtt",
    ".ass": "ass",
    ".ssa": "ass",
}
_MAX_ROWS = 40
_MAX_COLS = 12
_MAX_LINES = 20


def kind_for(content_type: str, url: str, payload: str) -> str:
    """Decide how to render a payload from its type, suffix and first bytes."""

    lowered = (content_type or "").lower()
    suffix = ""
    path = url.split("?", 1)[0].lower()
    for candidate in _SUFFIX_KINDS:
        if path.endswith(candidate):
            suffix = candidate
            break
    if "html" in lowered:
        return "html"
    if "ndjson" in lowered or "jsonl" in lowered:
        return "jsonl"
    if "json" in lowered:
        return "jsonl" if suffix in {".jsonl", ".ndjson"} else "json"
    if "subrip" in lowered or suffix == ".srt":
        return "srt"
    if "vtt" in lowered or suffix == ".vtt":
        return "vtt"
    if suffix in {".ass", ".ssa"}:
        return "ass"
    if "pdf" in lowered:
        return "pdf"
    if "tab-separated" in lowered or "tsv" in lowered:
        return "tsv"
    if "csv" in lowered:
        return "csv"
    if "markdown" in lowered:
        return "markdown"
    if "xml" in lowered or "rss" in lowered or "atom" in lowered:
        return "xml"
    if suffix:
        return _SUFFIX_KINDS[suffix]
    if "text" in lowered or not lowered:
        if looks_like_html(payload):
            return "html"
        head = payload.lstrip()[:1]
        if head in {"{", "["}:
            try:
                json.loads(payload)
            except ValueError:
                return "text"
            return "jsonl" if payload.count("\n") > 1 and "}\n{" in payload else "json"
        return "text"
    return "unknown"


def clamp(text: str, max_chars: int) -> str:
    """Cut to the budget with an explicit marker, never silently."""

    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    marker = f"\n[... truncated, {len(text) - max_chars} chars omitted]"
    room = max(0, max_chars - len(marker))
    return text[:room].rstrip() + marker


def csv_to_markdown(
    payload: str,
    *,
    delimiter: str = ",",
    max_chars: int = 20_000,
    max_rows: int = _MAX_ROWS,
    max_cols: int = _MAX_COLS,
) -> str:
    """Render a CSV/TSV table as a Markdown table, or say why not."""

    try:
        rows = list(csv.reader(io.StringIO(payload), delimiter=delimiter))
    except csv.Error as exc:
        return f"[table not parsed: {exc}]"
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return ""
    notes: list[str] = []
    total_rows = len(rows)
    rows = rows[: max_rows + 1]
    width = min(max(len(row) for row in rows), max_cols)
    if any(len(row) > width for row in rows):
        notes.append(f"columns truncated to {width}")
    if total_rows > len(rows):
        notes.append(f"showing {len(rows)} of {total_rows} rows")
    if any(len(row) != len(rows[0]) for row in rows):
        notes.append("ragged rows padded")
    cleaned: list[list[str]] = []
    for row in rows:
        cells = [cell.replace("|", "\\|").replace("\n", " ").strip() for cell in row[:width]]
        cells += [""] * (width - len(cells))
        cleaned.append(cells)
    if not cleaned or width == 0:
        return ""
    header = cleaned[0]
    body = cleaned[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    text = "\n".join(lines)
    if notes:
        text += "\n[" + "; ".join(notes) + "]"
    return clamp(text, max_chars)


def _summarise(value: Any, depth: int = 0, limit: int = 3) -> Any:
    if depth >= 2:
        if isinstance(value, dict):
            return f"object({len(value)} keys)"
        if isinstance(value, list):
            return f"array({len(value)} items)"
        return repr(value)[:80]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= limit:
                out["..."] = f"{len(value) - limit} more keys"
                break
            out[str(key)] = _summarise(item, depth + 1, limit)
        return out
    if isinstance(value, list):
        if not value:
            return []
        return {
            "count": len(value),
            "first": _summarise(value[0], depth + 1, limit),
        }
    return value


def json_summary(payload: str, max_chars: int = 20_000) -> str:
    """Pretty JSON when it fits; otherwise a truthful structural summary."""

    try:
        value = json.loads(payload)
    except ValueError as exc:
        return f"[invalid json: {exc}]\n" + clamp(payload, max_chars)
    pretty = json.dumps(value, ensure_ascii=False, indent=2)
    if len(pretty) <= max_chars:
        return pretty
    summary = json.dumps(_summarise(value), ensure_ascii=False, indent=2)
    note = (
        f"[json too large: {len(pretty)} chars; showing a depth-limited structural "
        "summary, not a byte cut]"
    )
    return clamp(f"{note}\n{summary}", max_chars)


def jsonl_summary(payload: str, max_chars: int = 20_000) -> str:
    """Parse JSONL line by line, report totals and truncation."""

    lines = [line for line in payload.splitlines() if line.strip()]
    parsed: list[Any] = []
    invalid = 0
    for line in lines:
        try:
            parsed.append(json.loads(line))
        except ValueError:
            invalid += 1
    notes = [f"{len(lines)} lines", f"{len(parsed)} parsed"]
    if invalid:
        notes.append(f"{invalid} invalid")
    rendered: list[str] = []
    used = 0
    for item in parsed[:_MAX_LINES]:
        chunk = json.dumps(item, ensure_ascii=False)
        if used + len(chunk) > max_chars:
            notes.append("stopped at the char budget")
            break
        rendered.append(chunk)
        used += len(chunk)
    if len(parsed) > len(rendered):
        notes.append(f"showing {len(rendered)} of {len(parsed)}")
    body = "\n".join(rendered)
    return clamp("[" + "; ".join(notes) + "]\n" + body, max_chars)


def _table_rows(table: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.xpath("./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr"):
        cells = [
            " ".join(cell.text_content().split())
            for cell in row.xpath("./th | ./td")
        ]
        if cells:
            rows.append(cells)
    return rows


def tables_to_markdown(
    html: str,
    *,
    max_chars: int = 20_000,
    max_tables: int = 5,
    max_rows: int = 25,
    max_cols: int = 10,
) -> str:
    """Keep HTML tables as Markdown instead of flattening rows into prose.

    Tables with merged cells are reported, not guessed: a colspan/rowspan table
    cannot be rendered as a rectangular grid without inventing cell positions.
    lxml is already a declared dependency; the reader adds no new one.
    """

    try:
        from lxml import html as lxml_html  # type: ignore[import-untyped]
    except Exception:  # noqa: BLE001 - optional parser
        return ""
    try:
        tree = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001 - not parseable HTML
        return ""
    blocks: list[str] = []
    notes: list[str] = []
    tables = tree.xpath("//table[not(ancestor::table)]")
    for index, table in enumerate(tables[:max_tables], start=1):
        merged = any(
            cell.get("colspan") or cell.get("rowspan")
            for cell in table.xpath(".//td | .//th")
        )
        if merged:
            notes.append(f"table {index} skipped: merged cells")
            continue
        rows = _table_rows(table)
        if len(rows) < 2:
            continue
        width = min(max(len(row) for row in rows), max_cols)
        if width == 0:
            continue
        if any(len(row) != width for row in rows):
            notes.append(f"table {index}: ragged rows padded")
        shown = rows[: max_rows + 1]
        if len(rows) > len(shown):
            notes.append(f"table {index}: showing {len(shown)} of {len(rows)} rows")
        grid = [[cell.replace("|", "\\|") for cell in row[:width]] + [""] * (width - len(row[:width]))
                for row in shown]
        lines = [
            "| " + " | ".join(grid[0]) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        lines.extend("| " + " | ".join(row) + " |" for row in grid[1:])
        blocks.append(f"[table {index}]\n" + "\n".join(lines))
    if len(tables) > max_tables:
        notes.append(f"only the first {max_tables} tables shown")
    text = "\n\n".join(blocks)
    if notes:
        text += "\n[" + "; ".join(notes) + "]"
    return clamp(text, max_chars)


def render_raw(kind: str, payload: str, max_chars: int) -> tuple[str, str]:
    """Return (text, method) for a non-HTML payload; ("","") when unsure."""

    if kind == "markdown":
        return clamp(payload, max_chars), "raw_markdown"
    if kind == "rst":
        return clamp(payload, max_chars), "raw_rst"
    if kind == "text":
        return clamp(payload, max_chars), "raw_text"
    if kind == "csv":
        return csv_to_markdown(payload, delimiter=",", max_chars=max_chars), "table_text"
    if kind == "tsv":
        return csv_to_markdown(payload, delimiter="\t", max_chars=max_chars), "table_text"
    if kind == "json":
        return json_summary(payload, max_chars), "json_text"
    if kind == "jsonl":
        return jsonl_summary(payload, max_chars), "jsonl_text"
    if kind in {"srt", "vtt", "ass"}:
        return subtitle_text(payload, kind, max_chars), "subtitle_text"
    return "", ""


def looks_like_html(payload: str) -> bool:
    head = re.sub(r"^\s+", "", payload[:200]).lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<body" in head[:400]


def _clock(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _parse_clock(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return 0.0
    while len(numbers) < 3:
        numbers.insert(0, 0.0)
    return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def _cue_lines(payload: str, kind: str) -> list[tuple[float, str]]:
    cues: list[tuple[float, str]] = []
    if kind in {"srt", "vtt"}:
        time_pattern = re.compile(
            r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})"
        )
        current: float | None = None
        for raw in payload.splitlines():
            line = raw.strip()
            match = time_pattern.search(line)
            if match:
                current = _parse_clock(match.group(1))
                continue
            if not line or line.isdigit() or line.upper() == "WEBVTT":
                continue
            if current is None:
                continue
            text = re.sub(r"<[^>]+>", "", line)
            text = " ".join(text.split())
            if not text:
                continue
            if cues and cues[-1][0] == current and cues[-1][1] == text:
                continue
            cues.append((current, text))
    elif kind == "ass":
        in_events = False
        fields: list[str] = []
        for raw in payload.splitlines():
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                in_events = line.lower() == "[events]"
                continue
            if not in_events:
                continue
            if line.lower().startswith("format:"):
                fields = [part.strip().lower() for part in line.split(":", 1)[1].split(",")]
                continue
            if not line.lower().startswith("dialogue:"):
                continue
            parts = line.split(":", 1)[1].split(",", max(0, len(fields) - 1) if fields else 9)
            if fields and "start" in fields and "text" in fields:
                try:
                    when = _parse_clock(parts[fields.index("start")])
                    text = parts[fields.index("text")]
                except (IndexError, ValueError):
                    continue
            else:
                if len(parts) < 10:
                    continue
                when = _parse_clock(parts[1])
                text = parts[9]
            text = re.sub(r"\{[^}]*\}", "", text)
            text = " ".join(text.replace("\\N", " ").split())
            if text:
                cues.append((when, text))
    return cues


def subtitle_text(payload: str, kind: str, max_chars: int = 20_000) -> str:
    """Render SRT/VTT/ASS cues with timestamps, dropping markup only."""

    cues = _cue_lines(payload, kind)
    if not cues:
        return ""
    header = f"[subtitles] {len(cues)} cues ({kind}), timestamps preserved"
    lines = [f"[{_clock(when)}] {text}"[:600] for when, text in cues]
    return clamp(header + "\n" + "\n".join(lines), max_chars)


def pdf_text(data: bytes, max_chars: int = 20_000, max_pages: int = 20) -> str:
    """Extract plain text from a PDF; layout, tables and images are not kept."""

    try:
        from pypdf import PdfReader
    except Exception:  # noqa: BLE001 - optional dependency
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:  # noqa: BLE001 - not a readable PDF
        return ""
    total = len(reader.pages)
    pages: list[str] = []
    for index, page in enumerate(reader.pages[:max_pages], start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - one bad page must not drop the rest
            continue
        text = " ".join(text.split())
        if text:
            pages.append(f"[page {index}]\n{text}")
    if not pages:
        return ""
    info = getattr(reader, "metadata", None) or {}
    title = str(getattr(info, "title", "") or "")
    header = (
        f"[pdf] {total} pages; extracted {min(total, max_pages)} as plain text "
        "(layout, tables and images are not preserved)"
    )
    if title.strip():
        header += f"; title={title.strip()[:160]}"
    return clamp(header + "\n" + "\n\n".join(pages), max_chars)


def page_toc(html: str, base_url: str, limit: int = 40, max_chars: int = 2000) -> str:
    """List document headings so a long page can be read by section."""

    try:
        from lxml import html as lxml_html  # type: ignore[import-untyped]
    except Exception:  # noqa: BLE001 - optional parser
        return ""
    try:
        tree = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001 - not parseable HTML
        return ""
    rows: list[str] = []
    for heading in tree.xpath("//h1 | //h2 | //h3"):
        text = " ".join(heading.text_content().split())[:120]
        if not text:
            continue
        anchor = heading.get("id") or ""
        if not anchor:
            links = heading.xpath(".//a[@id or @name]")
            if links:
                anchor = links[0].get("id") or links[0].get("name") or ""
        level = str(heading.tag).upper()
        suffix = f" — {base_url.split('#', 1)[0]}#{anchor}" if anchor else ""
        rows.append(f"- {level} {text}{suffix}")
        if len(rows) >= limit:
            break
    if len(rows) < 3:
        return ""
    return clamp("[toc]\n" + "\n".join(rows), max_chars)


def section_text(html: str, fragment: str, max_chars: int = 20_000) -> str:
    """Plain text of one anchored section, for very long documents."""

    if not fragment:
        return ""
    try:
        from lxml import html as lxml_html  # type: ignore[import-untyped]
    except Exception:  # noqa: BLE001 - optional parser
        return ""
    try:
        tree = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001 - not parseable HTML
        return ""
    matches = tree.xpath("//*[@id=$fragment]", fragment=fragment) or tree.xpath(
        "//*[@name=$fragment]", fragment=fragment
    )
    if not matches:
        return ""
    heading = matches[0]
    ranks = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
    rank = ranks.get(str(heading.tag).lower(), 4)
    parts = [" ".join(heading.text_content().split())]
    for sibling in heading.itersiblings():
        tag = str(sibling.tag).lower() if isinstance(sibling.tag, str) else ""
        if ranks.get(tag, 99) <= rank:
            break
        text = " ".join(sibling.text_content().split())
        if text:
            parts.append(text)
    text = " ".join(part for part in parts if part)
    if not text.strip():
        return ""
    return clamp(f"[section #{fragment}]\n{text}", max_chars)


#: Annotation containers whose links are navigation, not article citations.
_NAV_TAGS = {"nav", "header", "footer", "aside"}
_HINT_PATTERN = re.compile(
    r"doi|arxiv|paper|preprint|source|original|via|reference|report|"
    r"论文|原文|出处|来源|参考|报告",
    re.IGNORECASE,
)


def _json_ld_values(value: Any, key: str, out: list[str], depth: int = 0) -> None:
    if depth > 4:
        return
    if isinstance(value, list):
        for item in value:
            _json_ld_values(item, key, out, depth + 1)
        return
    if not isinstance(value, dict):
        return
    item = value.get(key)
    if isinstance(item, str) and item.strip():
        out.append(item.strip())
    elif isinstance(item, dict):
        name = item.get("name") or item.get("@id")
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    elif isinstance(item, list):
        for entry in item:
            _json_ld_values(entry, "name", out, depth + 1)
    for child in value.get("@graph") or []:
        _json_ld_values(child, key, out, depth + 1)


def page_metadata(html: str) -> str:
    """Return author and dates the page declares, labelled as unverified.

    JSON-LD is the primary source; meta tags cover pages without it. Values are
    reported exactly as declared, never as independently verified facts.
    """

    try:
        from lxml import html as lxml_html  # type: ignore[import-untyped]
    except Exception:  # noqa: BLE001 - optional parser
        return ""
    try:
        tree = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001 - not parseable HTML
        return ""
    authors: list[str] = []
    published: list[str] = []
    modified: list[str] = []
    for block in tree.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            value = json.loads(block)
        except ValueError:
            continue
        _json_ld_values(value, "author", authors)
        _json_ld_values(value, "datePublished", published)
        _json_ld_values(value, "dateModified", modified)
    if not authors:
        for node in tree.xpath('//meta[translate(@name,"AUTHOR","author")="author"]/@content'):
            if node.strip():
                authors.append(node.strip())
    if not published:
        published = [
            node.strip()
            for node in tree.xpath(
                '//meta[@property="article:published_time" or '
                '@property="og:published_time"]/@content'
            )
            if node.strip()
        ]
    if not modified:
        modified = [
            node.strip()
            for node in tree.xpath(
                '//meta[@property="article:modified_time" or '
                '@property="og:updated_time"]/@content'
            )
            if node.strip()
        ]
    parts = []
    if authors:
        parts.append("author=" + ", ".join(dict.fromkeys(authors))[:160])
    if published:
        parts.append("published=" + published[0][:40])
    if modified:
        parts.append("modified=" + modified[0][:40])
    if not parts:
        return ""
    return (
        "[metadata] " + "; ".join(parts)
        + " (declared by the page, not independently verified)"
    )


def citation_links(
    html: str,
    base_url: str,
    *,
    max_chars: int = 4000,
    limit: int = 25,
) -> str:
    """List outbound links with a positional hint about their role.

    Body links are the ones the article itself cites; links inside nav, header,
    footer or aside are navigation or recommendations. The hint is positional,
    not a claim that the target supports the article. Nothing is fetched.
    """

    try:
        from lxml import html as lxml_html  # type: ignore[import-untyped]
    except Exception:  # noqa: BLE001 - optional parser
        return ""
    try:
        tree = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001 - not parseable HTML
        return ""
    host = urllib.parse.urlsplit(base_url).hostname or ""
    body: list[tuple[int, str]] = []
    navigation: list[tuple[int, str]] = []
    seen: set[str] = set()
    for anchor in tree.xpath("//a[@href]"):
        raw = str(anchor.get("href") or "").strip()
        if not raw or raw.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        url = urllib.parse.urljoin(base_url, raw)
        if urllib.parse.urlsplit(url).scheme not in {"http", "https"}:
            continue
        if url in seen:
            continue
        seen.add(url)
        text = " ".join(anchor.text_content().split())[:120] or str(anchor.get("title") or "")[:120]
        if not text:
            continue
        parent_nav = False
        parent = anchor.getparent()
        while parent is not None and parent.tag:
            if str(parent.tag).lower() in _NAV_TAGS:
                parent_nav = True
                break
            parent = parent.getparent()
        hint = bool(_HINT_PATTERN.search(f"{text} {url}"))
        relation = "nav" if parent_nav else "body"
        if urllib.parse.urlsplit(url).hostname == host:
            relation += ",same-site"
        prefix = f"[{relation}{',cite-hint' if hint else ''}]"
        line = f"{prefix} {text} — {url}"
        (navigation if parent_nav else body).append((0 if hint else 1, line))
    body.sort(key=lambda item: item[0])
    navigation.sort(key=lambda item: item[0])
    rows = [line for _, line in body[:limit]]
    rows += [line for _, line in navigation[:5]]
    if not rows:
        return ""
    notes = [f"{len(body)} body links", f"{len(navigation)} nav links"]
    if len(body) > limit:
        notes.append(f"showing {limit} of {len(body)} body links")
    return clamp("[links] " + "; ".join(notes) + "\n" + "\n".join(rows), max_chars)


def feed_summary(payload: str, max_chars: int = 20_000, limit: int = 20) -> str:
    """Render an RSS 2.0 or Atom feed as a bounded entry list."""

    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return ""
    atom = "{http://www.w3.org/2005/Atom}"
    entries: list[str] = []
    if root.tag.endswith("feed"):
        items = root.findall(f"{atom}entry")
        for item in items[:limit]:
            title = (item.findtext(f"{atom}title") or "").strip()
            link = ""
            audio = ""
            for node in item.findall(f"{atom}link"):
                if node.get("rel") in {"alternate", None} and not link:
                    link = node.get("href") or ""
                if node.get("rel") == "enclosure":
                    audio = node.get("href") or ""
            when = (item.findtext(f"{atom}updated") or item.findtext(f"{atom}published") or "").strip()
            summary = (item.findtext(f"{atom}summary") or "").strip()
            entries.append(_feed_line(title, link, when, summary, audio))
    else:
        channel = root.find("channel")
        if channel is None:
            channel = root
        items = channel.findall("item")
        for item in items[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            when = (item.findtext("pubDate") or "").strip()
            summary = (item.findtext("description") or "").strip()
            enclosure = item.find("enclosure")
            audio = (enclosure.get("url") or "") if enclosure is not None else ""
            transcript = ""
            for child in item.iter():
                if str(child.tag).lower().endswith("transcript") and child.get("url"):
                    transcript = child.get("url") or ""
                    break
            entries.append(_feed_line(title, link, when, summary, audio, transcript))
    if not entries:
        return ""
    header = f"[feed] {len(items)} entries, showing {len(entries)}"
    return clamp(header + "\n" + "\n".join(entries), max_chars)


def _feed_line(
    title: str, link: str, when: str, summary: str,
    audio: str = "", transcript: str = "",
) -> str:
    text = re.sub(r"<[^>]+>", " ", summary or "")
    text = " ".join(text.split())[:240]
    parts = [f"- {title[:160]}"]
    if when:
        parts.append(f"({when[:32]})")
    if link:
        parts.append(link)
    if audio:
        parts.append(f"audio={audio} (not transcribed)")
    if transcript:
        parts.append(f"transcript={transcript}")
    if text:
        parts.append(f":: {text}")
    return " ".join(parts)
