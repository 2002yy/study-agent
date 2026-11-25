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
    for row in table.find_all("tr"):
        cells = [
            cell.get_text(" ", strip=True)
            for cell in row.find_all(["th", "td"])
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
    """

    try:
        from bs4 import BeautifulSoup
    except Exception:  # noqa: BLE001 - optional parser
        return ""
    soup = BeautifulSoup(html, "html.parser")
    blocks: list[str] = []
    notes: list[str] = []
    tables = [table for table in soup.find_all("table") if not table.find_parent("table")]
    for index, table in enumerate(tables[:max_tables], start=1):
        merged = any(
            cell.get("colspan") or cell.get("rowspan")
            for cell in table.find_all(["td", "th"])
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
    return "", ""


def looks_like_html(payload: str) -> bool:
    head = re.sub(r"^\s+", "", payload[:200]).lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<body" in head[:400]
