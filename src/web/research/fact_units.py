"""Experiment-only fact units for the structure + 24 pre-check.

This module is **not wired into production**. It exists to answer, without a
model call, whether a structure-aware unit builder can meet the four conditions
the segmentation review set before any paid comparison:

* a heading that states something is kept even when it contains no digit;
* a table row keeps the header names that give its values meaning;
* a code block stays one unit instead of being shredded into statement lines;
* the unit count, the rendered prompt size and the A2 candidate budget are
  checked *before* work starts, and an over-budget answer is refused rather
  than truncated.

Every unit records the span it came from, so a reviewer can map a unit back to
the answer text. Dropped headings are returned, not silently discarded.

The difference from :mod:`tools.segmentation_coverage` is intentional: that
probe measured cheap rules; this builder is the candidate a paid comparison
would actually run, so it pays for correctness with more units.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

#: Experiment budget: the review approved `structure + 24` as the main group.
DEFAULT_MAX_UNITS = 24
#: A2 gives every unit at most this many candidate passages.
CANDIDATES_PER_UNIT = 3
#: The binder renders all units into one block; refuse rather than truncate.
MAX_PROMPT_CHARS = 16000

REASON_UNIT_BUDGET = "unit_budget_exceeded"
REASON_PROMPT_BUDGET = "prompt_budget_exceeded"

_FENCE = re.compile(r"^\s*```")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s*(.*)$")
_TABLE_ROW = re.compile(r"^\s*\|(.*)\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_ORDINAL_ONLY = re.compile(r"^(?:[一二三四五六七八九十百]+[、.]?|\d+[.)、]?|\(\d+\))$")
_SENTENCE = re.compile(r"(?<=[。！？；!?;\n])|(?<=[.])(?=\s|$)")


@dataclass(frozen=True)
class FactUnit:
    """One thing a claim could be checked against, with its source span."""

    text: str
    kind: str
    start: int
    end: int
    source: str
    context: str = ""

    def as_record(self) -> dict[str, object]:
        return {
            "text": self.text,
            "kind": self.kind,
            "start": self.start,
            "end": self.end,
            "context": self.context,
        }


@dataclass(frozen=True)
class FactUnits:
    units: tuple[FactUnit, ...]
    dropped: tuple[FactUnit, ...]
    reason: str
    max_units: int
    prompt_chars: int = 0
    candidate_budget: int = 0
    counted_units: int = 0
    kinds: dict[str, int] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return not self.reason


def build_fact_units(
    answer: str,
    *,
    max_units: int = DEFAULT_MAX_UNITS,
    max_prompt_chars: int = MAX_PROMPT_CHARS,
) -> FactUnits:
    """Build fact units, or refuse when the answer cannot be covered in budget."""

    text = str(answer or "")
    units: list[FactUnit] = []
    dropped: list[FactUnit] = []
    offset = 0
    fence_open = False
    fence_start = 0
    fence_lines: list[str] = []
    table_header: tuple[str, ...] = ()

    def add(unit: FactUnit) -> None:
        units.append(unit)

    for line in text.splitlines(keepends=True):
        start = offset
        offset += len(line)
        stripped = line.strip()
        end = start + len(line.rstrip("\r\n"))

        if _FENCE.match(stripped):
            if fence_open:
                block = "\n".join(fence_lines)
                add(
                    FactUnit(
                        text=block.strip(),
                        kind="code",
                        start=fence_start,
                        end=end,
                        source=block,
                    )
                )
                fence_open = False
                fence_lines = []
            else:
                fence_open = True
                fence_start = start
            continue
        if fence_open:
            fence_lines.append(line.rstrip("\r\n"))
            continue
        if not stripped:
            continue

        heading = _HEADING.match(stripped)
        if heading:
            body = heading.group(2).strip()
            unit = FactUnit(
                text=body,
                kind="heading",
                start=start,
                end=end,
                source=stripped,
            )
            if _ORDINAL_ONLY.match(body):
                # A bare numbering heading carries no statement. It is recorded
                # as dropped so the removal is auditable, never silent.
                dropped.append(unit)
            else:
                add(unit)
            table_header = ()
            continue

        if _TABLE_RULE.match(stripped):
            continue
        row = _TABLE_ROW.match(stripped)
        if row:
            cells = tuple(cell.strip() for cell in row.group(1).split("|"))
            if not table_header:
                table_header = cells
                add(
                    FactUnit(
                        text=stripped,
                        kind="table_header",
                        start=start,
                        end=end,
                        source=stripped,
                    )
                )
                continue
            add(_table_unit(cells, table_header, start, end, stripped))
            continue

        item = _LIST_ITEM.match(stripped)
        if item:
            table_header = ()
            add(
                FactUnit(
                    text=stripped[item.end() :].strip(),
                    kind="list_item",
                    start=start,
                    end=end,
                    source=stripped,
                )
            )
            continue

        table_header = ()
        for segment_start, segment in _sentences(stripped):
            add(
                FactUnit(
                    text=segment,
                    kind="prose",
                    start=start + segment_start,
                    end=start + segment_start + len(segment),
                    source=stripped,
                )
            )

    if fence_open and fence_lines:
        block = "\n".join(fence_lines)
        add(
            FactUnit(
                text=block.strip(),
                kind="code",
                start=fence_start,
                end=len(text),
                source=block,
            )
        )

    kinds: dict[str, int] = {}
    for unit in units:
        kinds[unit.kind] = kinds.get(unit.kind, 0) + 1
    prompt_chars = len(_numbered(units))
    candidate_budget = max(0, int(max_units)) * CANDIDATES_PER_UNIT
    reason = ""
    if len(units) > max(0, int(max_units)):
        reason = REASON_UNIT_BUDGET
    elif prompt_chars > max_prompt_chars:
        reason = REASON_PROMPT_BUDGET
    return FactUnits(
        units=() if reason else tuple(units),
        dropped=tuple(dropped),
        reason=reason,
        max_units=max(0, int(max_units)),
        prompt_chars=prompt_chars,
        candidate_budget=candidate_budget,
        counted_units=len(units),
        kinds=kinds,
    )


def _table_unit(
    cells: Sequence[str],
    header: Sequence[str],
    start: int,
    end: int,
    source: str,
) -> FactUnit:
    """A row unit keeps the header names, so a value is never context-free."""

    pairs = [
        f"{header[index] or f'列{index + 1}'}: {value}"
        for index, value in enumerate(cells)
        if value
    ]
    return FactUnit(
        text="；".join(pairs) or source,
        kind="table_row",
        start=start,
        end=end,
        source=source,
        context=" | ".join(header),
    )


def _sentences(text: str) -> tuple[tuple[int, str], ...]:
    parts: list[tuple[int, str]] = []
    cursor = 0
    for match in _SENTENCE.finditer(text):
        end = match.end()
        piece = text[cursor:end].strip()
        if piece:
            leading = len(text[cursor:end]) - len(text[cursor:end].lstrip())
            parts.append((cursor + leading, piece))
        cursor = end
    tail = text[cursor:].strip()
    if tail:
        leading = len(text[cursor:]) - len(text[cursor:].lstrip())
        parts.append((cursor + leading, tail))
    return tuple(parts)


def _numbered(units: Sequence[FactUnit]) -> str:
    return "\n".join(f"[s{index}] {unit.text}" for index, unit in enumerate(units, 1))
