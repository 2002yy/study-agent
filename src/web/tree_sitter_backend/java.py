from __future__ import annotations

import re
from typing import Any

from .common import (
    BaseCollector,
    child_text,
    inheritance_names,
    line_range,
    node_text,
    scope_name,
)
from .models import ParsedImport


def _import(text: str, start: int, end: int) -> ParsedImport | None:
    normalized = " ".join(text.strip().split()).rstrip(";")
    match = re.match(r"import\s+(static\s+)?(.+)$", normalized)
    if not match:
        return None
    module = match.group(2).strip()
    return ParsedImport(
        module=module,
        names=(module.rsplit(".", 1)[-1],),
        kind="static_import" if match.group(1) else "import",
        start_line=start,
        end_line=end,
    )


class JavaCollector(BaseCollector):
    def handle(
        self,
        node: Any,
        scope: list[tuple[str, str]],
    ) -> tuple[str, str] | None:
        node_type = str(node.type)
        type_kinds = {
            "class_declaration": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
            "record_declaration": "record",
        }
        if node_type in type_kinds:
            name = child_text(self.source, node, "name")
            added = self.add_symbol(node, scope, name=name, kind=type_kinds[node_type])
            qualified = f"{scope_name(scope)}.{name}" if scope else name
            for field, kind in (("superclass", "extends"), ("interfaces", "implements")):
                target = node.child_by_field_name(field)
                if target is not None:
                    self.add_inheritance(
                        target,
                        child=qualified,
                        parents=inheritance_names(node_text(self.source, target)),
                        kind=kind,
                    )
            return added
        if node_type in {"method_declaration", "constructor_declaration"}:
            kind = "constructor" if node_type == "constructor_declaration" else "method"
            return self.add_symbol(
                node,
                scope,
                name=child_text(self.source, node, "name"),
                kind=kind,
            )
        if node_type == "import_declaration":
            start, end = line_range(node)
            parsed = _import(node_text(self.source, node), start, end)
            if parsed is not None:
                self.imports.append(parsed)
        if node_type == "method_invocation":
            name = child_text(self.source, node, "name")
            obj = child_text(self.source, node, "object")
            self.add_call(node, scope, callee=f"{obj}.{name}" if obj else name)
        if node_type == "object_creation_expression":
            self.add_call(
                node,
                scope,
                callee=child_text(self.source, node, "type"),
                kind="constructor",
            )
        return None
