from __future__ import annotations

import re
from typing import Any

from .models import ParsedCall, ParsedInheritance, ParsedImport, ParsedSymbol

_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_DOTTED_IDENTIFIER = re.compile(
    r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*"
)


def node_text(source: bytes, node: Any | None) -> str:
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def child_text(source: bytes, node: Any, field: str) -> str:
    return node_text(source, node.child_by_field_name(field)).strip()


def line_range(node: Any) -> tuple[int, int]:
    start = int(node.start_point[0]) + 1
    end = int(node.end_point[0]) + 1
    return max(1, start), max(start, end)


def signature(text: str, *, max_chars: int = 300) -> str:
    focused = " ".join(text.strip().split())
    if "{" in focused:
        focused = focused.split("{", 1)[0].rstrip()
    return focused[:max_chars]


def scope_name(scope: list[tuple[str, str]]) -> str:
    return ".".join(name for name, _kind in scope)


def nearest_callable(scope: list[tuple[str, str]]) -> str:
    for index in range(len(scope) - 1, -1, -1):
        if scope[index][1] in {"function", "method", "constructor"}:
            return ".".join(name for name, _kind in scope[: index + 1])
    return ""


def named_identifiers(text: str) -> tuple[str, ...]:
    ignored = {
        "as",
        "default",
        "export",
        "extends",
        "from",
        "import",
        "implements",
        "interface",
        "static",
        "type",
    }
    return tuple(
        dict.fromkeys(token for token in _IDENTIFIER.findall(text) if token not in ignored)
    )


def inheritance_names(text: str) -> tuple[str, ...]:
    ignored = {"class", "extends", "implements", "interface", "with"}
    return tuple(
        dict.fromkeys(
            name for name in _DOTTED_IDENTIFIER.findall(text) if name not in ignored
        )
    )


class BaseCollector:
    def __init__(self, source: bytes) -> None:
        self.source = source
        self.symbols: list[ParsedSymbol] = []
        self.imports: list[ParsedImport] = []
        self.calls: list[ParsedCall] = []
        self.inheritance: list[ParsedInheritance] = []

    def add_symbol(
        self,
        node: Any,
        scope: list[tuple[str, str]],
        *,
        name: str,
        kind: str,
    ) -> tuple[str, str] | None:
        if not name:
            return None
        parent = scope_name(scope)
        qualified = f"{parent}.{name}" if parent else name
        start, end = line_range(node)
        self.symbols.append(
            ParsedSymbol(
                name=name,
                qualified_name=qualified,
                kind=kind,
                signature=signature(node_text(self.source, node)),
                parent=parent,
                start_line=start,
                end_line=end,
            )
        )
        return name, kind

    def add_call(
        self,
        node: Any,
        scope: list[tuple[str, str]],
        *,
        callee: str,
        kind: str = "call",
    ) -> None:
        focused = callee.strip()
        if not focused:
            return
        start, end = line_range(node)
        self.calls.append(
            ParsedCall(
                callee=focused[:300],
                caller=nearest_callable(scope) or scope_name(scope),
                kind=kind,
                start_line=start,
                end_line=end,
            )
        )

    def add_inheritance(
        self,
        node: Any,
        *,
        child: str,
        parents: tuple[str, ...],
        kind: str,
    ) -> None:
        start, end = line_range(node)
        for parent in parents:
            if child and parent and child != parent:
                self.inheritance.append(
                    ParsedInheritance(
                        child=child,
                        parent=parent,
                        kind=kind,
                        start_line=start,
                        end_line=end,
                    )
                )

    def handle(
        self,
        node: Any,
        scope: list[tuple[str, str]],
    ) -> tuple[str, str] | None:
        raise NotImplementedError

    def walk(self, node: Any, scope: list[tuple[str, str]] | None = None) -> None:
        active_scope = list(scope or [])
        next_scope = self.handle(node, active_scope)
        child_scope = active_scope + ([next_scope] if next_scope else [])
        for child in node.named_children:
            self.walk(child, child_scope)
