"""Structured source analysis over persisted GitHub repository snapshots.

Python uses the standard-library AST. JavaScript and TypeScript use conservative
patterns until a tree-sitter/LSP backend is added. Public result contracts are
parser-agnostic so that later parser upgrades do not break API consumers.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import posixpath
from pathlib import PurePosixPath
import re
from typing import Any, Iterable


_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_JS_DECLARATIONS = (
    (
        "class",
        re.compile(
            r"^\s*(?:export\s+(?:default\s+)?)?class\s+"
            r"([A-Za-z_$][A-Za-z0-9_$]*)",
            re.MULTILINE,
        ),
    ),
    (
        "function",
        re.compile(
            r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+"
            r"([A-Za-z_$][A-Za-z0-9_$]*)",
            re.MULTILINE,
        ),
    ),
    (
        "interface",
        re.compile(
            r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][A-Za-z0-9_$]*)",
            re.MULTILINE,
        ),
    ),
    (
        "type",
        re.compile(
            r"^\s*(?:export\s+)?type\s+([A-Za-z_$][A-Za-z0-9_$]*)",
            re.MULTILINE,
        ),
    ),
    (
        "enum",
        re.compile(
            r"^\s*(?:export\s+)?enum\s+([A-Za-z_$][A-Za-z0-9_$]*)",
            re.MULTILINE,
        ),
    ),
    (
        "variable",
        re.compile(
            r"^\s*(?:export\s+)?(?:const|let|var)\s+"
            r"([A-Za-z_$][A-Za-z0-9_$]*)",
            re.MULTILINE,
        ),
    ),
)
_JS_IMPORT = re.compile(
    r"^\s*import\s+(?:(?P<what>.+?)\s+from\s+)?"
    r"[\"'](?P<module>[^\"']+)[\"']",
    re.MULTILINE,
)
_JS_EXPORT_FROM = re.compile(
    r"^\s*export\s+(?P<what>.+?)\s+from\s+"
    r"[\"'](?P<module>[^\"']+)[\"']",
    re.MULTILINE,
)
_JS_REQUIRE = re.compile(
    r"^\s*(?:const|let|var)\s+(?P<what>[^=]+?)\s*=\s*"
    r"require\([\"'](?P<module>[^\"']+)[\"']\)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class EvidenceRef:
    repository: str
    ref: str
    tree_sha: str
    path: str
    file_sha: str
    start_line: int
    end_line: int
    symbol: str = ""
    kind: str = "source"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodeSymbol:
    name: str
    qualified_name: str
    kind: str
    language: str
    signature: str
    parent: str
    evidence: EvidenceRef

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = self.evidence.to_dict()
        return payload


@dataclass(frozen=True)
class ImportEdge:
    module: str
    names: tuple[str, ...]
    kind: str
    resolved_path: str
    evidence: EvidenceRef

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["names"] = list(self.names)
        payload["evidence"] = self.evidence.to_dict()
        return payload


@dataclass(frozen=True)
class StructuredFile:
    path: str
    file_sha: str
    language: str
    line_count: int
    symbols: tuple[CodeSymbol, ...]
    imports: tuple[ImportEdge, ...]
    parse_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "file_sha": self.file_sha,
            "language": self.language,
            "line_count": self.line_count,
            "symbols": [symbol.to_dict() for symbol in self.symbols],
            "imports": [edge.to_dict() for edge in self.imports],
            "parse_error": self.parse_error,
        }


def _language(path: str) -> str:
    suffix = PurePosixPath(path.casefold()).suffix
    if suffix == ".py":
        return "python"
    if suffix in {".ts", ".tsx"}:
        return "typescript"
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        return "javascript"
    return "text"


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _evidence(
    snapshot: dict[str, Any],
    raw_file: dict[str, Any],
    *,
    start_line: int,
    end_line: int,
    symbol: str = "",
    kind: str = "source",
) -> EvidenceRef:
    safe_start = max(1, int(start_line))
    return EvidenceRef(
        repository=str(snapshot.get("repository") or ""),
        ref=str(snapshot.get("ref") or ""),
        tree_sha=str(snapshot.get("tree_sha") or ""),
        path=str(raw_file.get("path") or ""),
        file_sha=str(raw_file.get("sha") or ""),
        start_line=safe_start,
        end_line=max(safe_start, int(end_line)),
        symbol=symbol,
        kind=kind,
    )


def evidence_for_range(
    snapshot: dict[str, Any],
    *,
    path: str,
    file_sha: str,
    start_line: int,
    end_line: int,
    symbol: str = "",
    kind: str = "source",
) -> dict[str, Any]:
    raw_file = {"path": path, "sha": file_sha}
    return _evidence(
        snapshot,
        raw_file,
        start_line=start_line,
        end_line=end_line,
        symbol=symbol,
        kind=kind,
    ).to_dict()


def _python_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        args = ast.unparse(node.args)
    except Exception:
        args = "..."
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({args})"


class _PythonCollector(ast.NodeVisitor):
    def __init__(self, snapshot: dict[str, Any], raw_file: dict[str, Any]) -> None:
        self.snapshot = snapshot
        self.raw_file = raw_file
        self.scope: list[tuple[str, str]] = []
        self.symbols: list[CodeSymbol] = []
        self.imports: list[ImportEdge] = []

    def _parent(self) -> str:
        return ".".join(name for name, _kind in self.scope)

    def _symbol(self, node: ast.AST, *, name: str, kind: str, signature: str) -> None:
        parent = self._parent()
        qualified = f"{parent}.{name}" if parent else name
        self.symbols.append(
            CodeSymbol(
                name=name,
                qualified_name=qualified,
                kind=kind,
                language="python",
                signature=signature,
                parent=parent,
                evidence=_evidence(
                    self.snapshot,
                    self.raw_file,
                    start_line=getattr(node, "lineno", 1),
                    end_line=getattr(
                        node,
                        "end_lineno",
                        getattr(node, "lineno", 1),
                    ),
                    symbol=qualified,
                    kind="definition",
                ),
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        bases = ""
        if node.bases:
            try:
                bases = "(" + ", ".join(
                    ast.unparse(base) for base in node.bases
                ) + ")"
            except Exception:
                bases = ""
        self._symbol(
            node,
            name=node.name,
            kind="class",
            signature=f"class {node.name}{bases}",
        )
        self.scope.append((node.name, "class"))
        self.generic_visit(node)
        self.scope.pop()

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> Any:
        parent_kind = self.scope[-1][1] if self.scope else ""
        kind = "method" if parent_kind == "class" else "function"
        self._symbol(
            node,
            name=node.name,
            kind=kind,
            signature=_python_signature(node),
        )
        self.scope.append((node.name, "function"))
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        return self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        return self._visit_function(node)

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            self.imports.append(
                ImportEdge(
                    module=alias.name,
                    names=(alias.asname or alias.name,),
                    kind="import",
                    resolved_path="",
                    evidence=_evidence(
                        self.snapshot,
                        self.raw_file,
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        kind="import",
                    ),
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        module = "." * int(node.level or 0) + str(node.module or "")
        self.imports.append(
            ImportEdge(
                module=module,
                names=tuple(alias.asname or alias.name for alias in node.names),
                kind="from_import",
                resolved_path="",
                evidence=_evidence(
                    self.snapshot,
                    self.raw_file,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    kind="import",
                ),
            )
        )


def _parse_python(
    snapshot: dict[str, Any],
    raw_file: dict[str, Any],
) -> StructuredFile:
    content = str(raw_file.get("content") or "")
    path = str(raw_file.get("path") or "")
    try:
        tree = ast.parse(content, filename=path)
        collector = _PythonCollector(snapshot, raw_file)
        collector.visit(tree)
        return StructuredFile(
            path=path,
            file_sha=str(raw_file.get("sha") or ""),
            language="python",
            line_count=max(1, len(content.splitlines())),
            symbols=tuple(collector.symbols),
            imports=tuple(collector.imports),
        )
    except SyntaxError as exc:
        return StructuredFile(
            path=path,
            file_sha=str(raw_file.get("sha") or ""),
            language="python",
            line_count=max(1, len(content.splitlines())),
            symbols=(),
            imports=(),
            parse_error=(
                f"SyntaxError: {exc.msg} at line {exc.lineno or 0}"
            ),
        )


def _js_names(value: str) -> tuple[str, ...]:
    ignored = {"as", "default", "from", "type"}
    return tuple(
        dict.fromkeys(
            token
            for token in _IDENTIFIER.findall(value or "")
            if token not in ignored
        )
    )


def _parse_javascript(
    snapshot: dict[str, Any],
    raw_file: dict[str, Any],
) -> StructuredFile:
    content = str(raw_file.get("content") or "")
    path = str(raw_file.get("path") or "")
    language = _language(path)
    symbols: list[CodeSymbol] = []
    imports: list[ImportEdge] = []
    for kind, pattern in _JS_DECLARATIONS:
        for match in pattern.finditer(content):
            name = match.group(1)
            line = _line_for_offset(content, match.start())
            symbols.append(
                CodeSymbol(
                    name=name,
                    qualified_name=name,
                    kind=kind,
                    language=language,
                    signature=match.group(0).strip(),
                    parent="",
                    evidence=_evidence(
                        snapshot,
                        raw_file,
                        start_line=line,
                        end_line=line,
                        symbol=name,
                        kind="definition",
                    ),
                )
            )
    for kind, pattern in (
        ("import", _JS_IMPORT),
        ("export_from", _JS_EXPORT_FROM),
        ("require", _JS_REQUIRE),
    ):
        for match in pattern.finditer(content):
            line = _line_for_offset(content, match.start())
            imports.append(
                ImportEdge(
                    module=str(match.group("module") or ""),
                    names=_js_names(
                        str(match.groupdict().get("what") or "")
                    ),
                    kind=kind,
                    resolved_path="",
                    evidence=_evidence(
                        snapshot,
                        raw_file,
                        start_line=line,
                        end_line=line,
                        kind="import",
                    ),
                )
            )
    symbols.sort(key=lambda item: (item.evidence.start_line, item.name))
    imports.sort(key=lambda item: (item.evidence.start_line, item.module))
    return StructuredFile(
        path=path,
        file_sha=str(raw_file.get("sha") or ""),
        language=language,
        line_count=max(1, len(content.splitlines())),
        symbols=tuple(symbols),
        imports=tuple(imports),
    )


def _normalized_path(value: str | PurePosixPath) -> str:
    return posixpath.normpath(str(value)).lstrip("./")


def _match_candidate(candidate: str, paths: set[str]) -> str:
    normalized = _normalized_path(candidate)
    if normalized in paths:
        return normalized
    suffix = f"/{normalized}"
    matches = sorted(path for path in paths if path.endswith(suffix))
    return matches[0] if len(matches) == 1 else ""


def _resolve_relative_import(
    source_path: str,
    module: str,
    paths: set[str],
) -> str:
    source = PurePosixPath(source_path)
    candidates: list[str] = []

    # JavaScript/TypeScript relative paths must be handled before Python's
    # leading-dot module notation.
    if module.startswith(("./", "../")):
        base = _normalized_path(source.parent / module)
        candidates.extend(
            [
                base,
                f"{base}.ts",
                f"{base}.tsx",
                f"{base}.js",
                f"{base}.jsx",
                f"{base}.mjs",
                f"{base}.cjs",
                f"{base}/index.ts",
                f"{base}/index.tsx",
                f"{base}/index.js",
                f"{base}/index.jsx",
            ]
        )
    elif module.startswith("."):
        level = len(module) - len(module.lstrip("."))
        remainder = module[level:]
        base = source.parent
        for _ in range(max(0, level - 1)):
            base = base.parent
        if remainder:
            base = base.joinpath(*remainder.split("."))
        candidates.extend([f"{base}.py", f"{base}/__init__.py"])
    else:
        dotted = module.replace(".", "/")
        candidates.extend(
            [
                f"{dotted}.py",
                f"{dotted}/__init__.py",
                f"{dotted}.ts",
                f"{dotted}.tsx",
                f"{dotted}.js",
                f"{dotted}.jsx",
                f"{dotted}/index.ts",
                f"{dotted}/index.tsx",
                f"{dotted}/index.js",
            ]
        )

    for candidate in candidates:
        matched = _match_candidate(candidate, paths)
        if matched:
            return matched
    return ""


def _identifier_variants(value: str) -> set[str]:
    focused = value.strip()
    if not focused:
        return set()
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", focused).casefold()
    return {
        focused,
        focused.casefold(),
        snake,
        snake.replace("_", ""),
        focused.replace("_", "").casefold(),
    }


class RepositoryStructureIndex:
    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = dict(snapshot)
        self.raw_files = {
            str(item.get("path") or ""): dict(item)
            for item in snapshot.get("files", [])
            if isinstance(item, dict) and str(item.get("path") or "")
        }
        paths = set(self.raw_files)
        self.files: dict[str, StructuredFile] = {}
        for raw in self.raw_files.values():
            parsed = self._parse_file(raw)
            imports = tuple(
                ImportEdge(
                    module=edge.module,
                    names=edge.names,
                    kind=edge.kind,
                    resolved_path=_resolve_relative_import(
                        parsed.path,
                        edge.module,
                        paths,
                    ),
                    evidence=edge.evidence,
                )
                for edge in parsed.imports
            )
            self.files[parsed.path] = StructuredFile(
                path=parsed.path,
                file_sha=parsed.file_sha,
                language=parsed.language,
                line_count=parsed.line_count,
                symbols=parsed.symbols,
                imports=imports,
                parse_error=parsed.parse_error,
            )
        self.symbols = tuple(
            symbol
            for structured_file in self.files.values()
            for symbol in structured_file.symbols
        )
        self.imports = tuple(
            edge
            for structured_file in self.files.values()
            for edge in structured_file.imports
        )

    def _parse_file(self, raw_file: dict[str, Any]) -> StructuredFile:
        language = _language(str(raw_file.get("path") or ""))
        if language == "python":
            return _parse_python(self.snapshot, raw_file)
        if language in {"javascript", "typescript"}:
            return _parse_javascript(self.snapshot, raw_file)
        content = str(raw_file.get("content") or "")
        return StructuredFile(
            path=str(raw_file.get("path") or ""),
            file_sha=str(raw_file.get("sha") or ""),
            language=language,
            line_count=max(1, len(content.splitlines())),
            symbols=(),
            imports=(),
        )

    def definitions(
        self,
        symbol: str,
        *,
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        variants = _identifier_variants(symbol)
        ranked: list[tuple[int, CodeSymbol]] = []
        for item in self.symbols:
            names = {
                item.name.casefold(),
                item.qualified_name.casefold(),
                item.name.replace("_", "").casefold(),
                item.qualified_name.replace("_", "").casefold(),
            }
            if item.name in variants or item.qualified_name in variants:
                score = 100
            elif names & variants:
                score = 90
            elif any(
                variant in name
                for variant in variants
                for name in names
            ):
                score = 50
            else:
                continue
            ranked.append((score, item))
        ranked.sort(
            key=lambda row: (
                -row[0],
                row[1].evidence.path,
                row[1].evidence.start_line,
            )
        )
        limit = max(1, min(top_k, 100))
        return [
            {**item.to_dict(), "score": score, "rank": index + 1}
            for index, (score, item) in enumerate(ranked[:limit])
        ]

    def references(
        self,
        symbol: str,
        *,
        top_k: int = 50,
    ) -> list[dict[str, Any]]:
        variants = _identifier_variants(symbol)
        patterns = [
            re.compile(
                rf"(?<![A-Za-z0-9_$]){re.escape(value)}"
                rf"(?![A-Za-z0-9_$])",
                re.IGNORECASE,
            )
            for value in variants
            if len(value) >= 2
        ]
        if not patterns:
            return []
        definition_lines = {
            (item.evidence.path, item.evidence.start_line)
            for item in self.symbols
            if item.name.casefold() in variants
            or item.name.replace("_", "").casefold() in variants
        }
        hits: list[dict[str, Any]] = []
        limit = max(1, min(top_k, 200))
        for path, raw_file in self.raw_files.items():
            content = str(raw_file.get("content") or "")
            for line_number, line in enumerate(content.splitlines(), start=1):
                if (path, line_number) in definition_lines:
                    continue
                if not any(pattern.search(line) for pattern in patterns):
                    continue
                hits.append(
                    {
                        "symbol": symbol,
                        "context": line.strip()[:500],
                        "evidence": _evidence(
                            self.snapshot,
                            raw_file,
                            start_line=line_number,
                            end_line=line_number,
                            symbol=symbol,
                            kind="reference",
                        ).to_dict(),
                    }
                )
                if len(hits) >= limit:
                    return hits
        return hits

    def related_files(
        self,
        symbol: str,
        *,
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        definitions = self.definitions(symbol, top_k=top_k)
        references = self.references(symbol, top_k=top_k * 3)
        paths: dict[str, set[str]] = {}
        for item in [*definitions, *references]:
            evidence = item.get("evidence") if isinstance(item, dict) else None
            if not isinstance(evidence, dict):
                continue
            path = str(evidence.get("path") or "")
            if path:
                paths.setdefault(path, set()).add(
                    str(evidence.get("kind") or "source")
                )
        seed_paths = set(paths)
        for edge in self.imports:
            if (
                edge.evidence.path in seed_paths
                or edge.resolved_path in seed_paths
            ):
                for path in (edge.evidence.path, edge.resolved_path):
                    if path:
                        paths.setdefault(path, set()).add("import")
        result = []
        for path in sorted(paths):
            structured_file = self.files.get(path)
            result.append(
                {
                    "path": path,
                    "reasons": sorted(paths[path]),
                    "language": (
                        structured_file.language if structured_file else "text"
                    ),
                    "file_sha": (
                        structured_file.file_sha if structured_file else ""
                    ),
                }
            )
        return result[: max(1, min(top_k, 100))]

    def inspect(self, symbol: str, *, top_k: int = 20) -> dict[str, Any]:
        return {
            "ok": True,
            "repository": str(self.snapshot.get("repository") or ""),
            "ref": str(self.snapshot.get("ref") or ""),
            "tree_sha": str(self.snapshot.get("tree_sha") or ""),
            "symbol": symbol,
            "definitions": self.definitions(symbol, top_k=top_k),
            "references": self.references(symbol, top_k=top_k * 3),
            "related_files": self.related_files(symbol, top_k=top_k),
            "stats": self.stats(),
        }

    def stats(self) -> dict[str, Any]:
        return {
            "file_count": len(self.files),
            "symbol_count": len(self.symbols),
            "import_count": len(self.imports),
            "resolved_import_count": sum(
                bool(edge.resolved_path) for edge in self.imports
            ),
            "parse_error_count": sum(
                bool(structured_file.parse_error)
                for structured_file in self.files.values()
            ),
            "languages": sorted(
                {structured_file.language for structured_file in self.files.values()}
            ),
            "parser": "python_ast+js_ts_fallback",
        }

    def file_summaries(self) -> Iterable[dict[str, Any]]:
        for path in sorted(self.files):
            yield self.files[path].to_dict()
