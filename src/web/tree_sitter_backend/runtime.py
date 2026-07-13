from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def supported_language(path: str) -> str:
    suffix = PurePosixPath(path.casefold()).suffix
    if suffix == ".py":
        return "python"
    if suffix in {".ts", ".tsx"}:
        return "typescript"
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        return "javascript"
    if suffix == ".java":
        return "java"
    return ""


def load_language(path: str) -> tuple[Any, str] | None:
    """Load fixed grammar wheels; never download parsers at runtime."""

    suffix = PurePosixPath(path.casefold()).suffix
    try:
        from tree_sitter import Language

        if suffix == ".py":
            import tree_sitter_python

            return Language(tree_sitter_python.language()), "tree_sitter_python"
        if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
            import tree_sitter_javascript

            return (
                Language(tree_sitter_javascript.language()),
                "tree_sitter_javascript",
            )
        if suffix in {".ts", ".tsx"}:
            import tree_sitter_typescript

            capsule = (
                tree_sitter_typescript.language_tsx()
                if suffix == ".tsx"
                else tree_sitter_typescript.language_typescript()
            )
            name = "tree_sitter_tsx" if suffix == ".tsx" else "tree_sitter_typescript"
            return Language(capsule), name
        if suffix == ".java":
            import tree_sitter_java

            return Language(tree_sitter_java.language()), "tree_sitter_java"
    except (ImportError, AttributeError, TypeError, ValueError):
        return None
    return None
