"""Optional Tree-sitter backend for repository structure extraction."""

from __future__ import annotations

from .java import JavaCollector
from .javascript import JavaScriptCollector
from .models import ParsedStructure
from .python import PythonCollector
from .runtime import load_language, supported_language


def parse_with_tree_sitter(path: str, content: str) -> ParsedStructure | None:
    language_name = supported_language(path)
    loaded = load_language(path)
    if not language_name or loaded is None:
        return None
    language, parser_name = loaded
    try:
        from tree_sitter import Parser

        source = content.encode("utf-8")
        tree = Parser(language).parse(source)
        if language_name == "python":
            collector = PythonCollector(source)
        elif language_name in {"javascript", "typescript"}:
            collector = JavaScriptCollector(source)
        else:
            collector = JavaCollector(source)
        collector.walk(tree.root_node)
        return ParsedStructure(
            language=language_name,
            parser=parser_name,
            symbols=tuple(
                sorted(collector.symbols, key=lambda item: (item.start_line, item.name))
            ),
            imports=tuple(
                sorted(collector.imports, key=lambda item: (item.start_line, item.module))
            ),
            calls=tuple(
                sorted(collector.calls, key=lambda item: (item.start_line, item.callee))
            ),
            inheritance=tuple(
                sorted(
                    collector.inheritance,
                    key=lambda item: (item.start_line, item.child, item.parent),
                )
            ),
            parse_error="tree_sitter_error_nodes" if tree.root_node.has_error else "",
        )
    except Exception as exc:
        return ParsedStructure(
            language=language_name,
            parser=parser_name,
            symbols=(),
            imports=(),
            calls=(),
            inheritance=(),
            parse_error=f"{type(exc).__name__}: {exc}",
        )


__all__ = ["ParsedStructure", "parse_with_tree_sitter", "supported_language"]
