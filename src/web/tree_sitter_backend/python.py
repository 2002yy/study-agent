from __future__ import annotations

import re
from typing import Any

from .common import (
    BaseCollector,
    child_text,
    inheritance_names,
    line_range,
    named_identifiers,
    node_text,
    scope_name,
)
from .models import ParsedImport


def _imports(text: str, start: int, end: int) -> list[ParsedImport]:
    stripped = " ".join(text.strip().split())
    if stripped.startswith("from "):
        match = re.match(r"from\s+([^\s]+)\s+import\s+(.+)$", stripped)
        if not match:
            return []
        return [
            ParsedImport(
                module=match.group(1),
                names=named_identifiers(match.group(2)),
                kind="from_import",
                start_line=start,
                end_line=end,
            )
        ]
    if not stripped.startswith("import "):
        return []
    result: list[ParsedImport] = []
    for item in stripped[len("import ") :].split(","):
        parts = item.strip().split()
        if not parts:
            continue
        module = parts[0]
        alias = parts[2] if len(parts) >= 3 and parts[1] == "as" else module
        result.append(
            ParsedImport(
                module=module,
                names=(alias,),
                kind="import",
                start_line=start,
                end_line=end,
            )
        )
    return result


class PythonCollector(BaseCollector):
    def handle(
        self,
        node: Any,
        scope: list[tuple[str, str]],
    ) -> tuple[str, str] | None:
        node_type = str(node.type)
        if node_type == "class_definition":
            name = child_text(self.source, node, "name")
            added = self.add_symbol(node, scope, name=name, kind="class")
            supers = node.child_by_field_name("superclasses")
            if supers is not None:
                qualified = f"{scope_name(scope)}.{name}" if scope else name
                self.add_inheritance(
                    supers,
                    child=qualified,
                    parents=inheritance_names(node_text(self.source, supers)),
                    kind="extends",
                )
            return added
        if node_type == "function_definition":
            name = child_text(self.source, node, "name")
            kind = "method" if scope and scope[-1][1] == "class" else "function"
            return self.add_symbol(node, scope, name=name, kind=kind)
        if node_type in {"import_statement", "import_from_statement"}:
            start, end = line_range(node)
            self.imports.extend(_imports(node_text(self.source, node), start, end))
        if node_type == "call":
            self.add_call(
                node,
                scope,
                callee=child_text(self.source, node, "function"),
            )
        return None
