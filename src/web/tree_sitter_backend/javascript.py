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


def _import(text: str, start: int, end: int) -> ParsedImport | None:
    normalized = " ".join(text.strip().split())
    match = re.search(r"(?:from\s+)?[\"']([^\"']+)[\"']", normalized)
    if not match:
        return None
    if normalized.startswith("export"):
        kind = "export_from"
    elif "require(" in normalized:
        kind = "require"
    else:
        kind = "import"
    return ParsedImport(
        module=match.group(1),
        names=named_identifiers(normalized[: match.start()]),
        kind=kind,
        start_line=start,
        end_line=end,
    )


class JavaScriptCollector(BaseCollector):
    def handle(
        self,
        node: Any,
        scope: list[tuple[str, str]],
    ) -> tuple[str, str] | None:
        node_type = str(node.type)
        if node_type in {"class_declaration", "abstract_class_declaration"}:
            name = child_text(self.source, node, "name")
            added = self.add_symbol(node, scope, name=name, kind="class")
            heritage = next(
                (child for child in node.named_children if child.type == "class_heritage"),
                None,
            )
            if heritage is not None:
                qualified = f"{scope_name(scope)}.{name}" if scope else name
                self.add_inheritance(
                    heritage,
                    child=qualified,
                    parents=inheritance_names(node_text(self.source, heritage)),
                    kind="extends",
                )
            return added
        if node_type == "interface_declaration":
            name = child_text(self.source, node, "name")
            added = self.add_symbol(node, scope, name=name, kind="interface")
            qualified = f"{scope_name(scope)}.{name}" if scope else name
            for child in node.named_children:
                if child.type in {"extends_type_clause", "class_heritage"}:
                    self.add_inheritance(
                        child,
                        child=qualified,
                        parents=inheritance_names(node_text(self.source, child)),
                        kind="extends",
                    )
            return added
        declarations = {
            "function_declaration": "function",
            "generator_function_declaration": "function",
            "method_definition": "method",
            "abstract_method_signature": "method",
        }
        if node_type in declarations:
            return self.add_symbol(
                node,
                scope,
                name=child_text(self.source, node, "name"),
                kind=declarations[node_type],
            )
        if node_type in {"type_alias_declaration", "enum_declaration"}:
            return self.add_symbol(
                node,
                scope,
                name=child_text(self.source, node, "name"),
                kind="type" if node_type.startswith("type_") else "enum",
            )
        if node_type == "variable_declarator":
            value = node.child_by_field_name("value")
            if value is not None and value.type in {
                "arrow_function",
                "function_expression",
                "generator_function",
            }:
                return self.add_symbol(
                    node,
                    scope,
                    name=child_text(self.source, node, "name"),
                    kind="function",
                )
        if node_type in {"import_statement", "export_statement"}:
            start, end = line_range(node)
            parsed = _import(node_text(self.source, node), start, end)
            if parsed is not None:
                self.imports.append(parsed)
        if node_type == "call_expression":
            callee = child_text(self.source, node, "function")
            self.add_call(
                node,
                scope,
                callee=callee,
                kind="require" if callee == "require" else "call",
            )
            if callee == "require":
                start, end = line_range(node)
                parsed = _import(node_text(self.source, node), start, end)
                if parsed is not None:
                    self.imports.append(parsed)
        if node_type == "new_expression":
            self.add_call(
                node,
                scope,
                callee=child_text(self.source, node, "constructor"),
                kind="constructor",
            )
        return None
