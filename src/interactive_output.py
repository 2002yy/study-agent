"""Conservatively wrap complete HTML from an explicitly restored UI turn.

This validates document framing, not executable safety or semantic correctness.
The existing UI sanitizer and sandbox remain the execution boundary.
"""

import json
import re
from html.parser import HTMLParser

from src.interactive_history import MAX_HTML_CHARS, find_interactive_versions
from src.interactive_restore import RestoreOutcome

_VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
_FENCE = re.compile(r"^ {0,3}(?:`{3,}|~{3,})", re.MULTILINE)
_HTML_FENCE = re.compile(r"^```html[ \t]*\n([\s\S]*?)\n```[ \t]*$", re.MULTILINE)


class _CompleteDocument(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[str] = []
        self.counts = {"html": 0, "head": 0, "body": 0}
        self.valid = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.counts:
            self.counts[tag] += 1
            if tag == "html":
                self.valid &= not self.stack
            else:
                self.valid &= self.stack == ["html"]
        elif not self.stack:
            self.valid = False
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if "svg" in self.stack and tag not in self.counts:
            return
        if tag not in _VOID:
            self.valid = False
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.valid = False
        else:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if not self.stack and data.strip():
            self.valid = False

    def handle_decl(self, decl: str) -> None:
        if self.stack or decl.lower() != "doctype html":
            self.valid = False


def normalize_interactive_output(
    reply: str, outcome: RestoreOutcome | None, finish_reason: str | None
) -> str:
    """Return one protocol document only when framing and saved identity agree."""
    if (
        outcome is None
        or not outcome.restorable
        or outcome.html is None
        or outcome.next_revision is None
        or finish_reason != "stop"
        or "study-ui" in reply
    ):
        return reply
    # Accept a single HTML fence with prose, or one bare document. Other
    # code fences and extra document roots make the answer ambiguous.
    match = _HTML_FENCE.search(reply)
    prefix = reply[: match.start()] if match else ""
    suffix = reply[match.end() :] if match else ""
    outside = prefix + suffix
    if _FENCE.search(outside) or re.search(r"<\s*(?:html|head|body)\b", outside, re.I):
        return reply
    html = match.group(1) if match else reply.strip()
    if _FENCE.search(html) or len(html) > MAX_HTML_CHARS:
        return reply
    parser = _CompleteDocument()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, AssertionError):
        return reply
    if not parser.valid or parser.stack or any(n != 1 for n in parser.counts.values()):
        return reply
    payload = {
        "type": "interactive",
        "id": outcome.request.id,
        "revision": outcome.next_revision,
        "title": "修复后的界面",
        "summary": "完整 HTML 已封装；运行效果待验证。",
        "html": html,
        "capabilities": list(outcome.capabilities),
    }
    wrapped = "```study-ui\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    return (
        prefix + wrapped + suffix
        if len(find_interactive_versions([{"role": "assistant", "content": wrapped}]))
        == 1
        else reply
    )
