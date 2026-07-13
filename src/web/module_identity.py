"""Snapshot-local module identities, re-export chains, and overload groups."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import hashlib
from pathlib import PurePosixPath
import re
from typing import Any

from src.web.module_aliases import load_module_aliases, resolve_snapshot_import
from src.web.repository_graph import RepositoryGraphIndex
from src.web.semantic_impact import SemanticImpactIndex, SymbolIdentity


_SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java"}
_TS_EXPORT_FROM = re.compile(
    r"\bexport\s+(?P<body>\*|\{[^}]*\})\s+from\s+['\"](?P<module>[^'\"]+)['\"]",
    re.MULTILINE,
)
_PYTHON_FROM_IMPORT = re.compile(
    r"^\s*from\s+(?P<module>[.A-Za-z0-9_]+)\s+import\s+(?P<body>[^\n#]+)",
    re.MULTILINE,
)
_JAVA_PACKAGE = re.compile(r"^\s*package\s+([A-Za-z_$][A-Za-z0-9_$.]*)\s*;", re.MULTILINE)


def _terminal(value: str) -> str:
    return str(value or "").strip().rsplit(".", 1)[-1]


def _normalized_path(path: str) -> str:
    return str(PurePosixPath(path)).lstrip("./")


def _module_name(path: str, content: str) -> tuple[str, str]:
    source = PurePosixPath(path)
    suffix = source.suffix.lower()
    if suffix == ".py":
        parts = list(source.with_suffix("").parts)
        while parts and parts[0] in {"src", "lib", "python"}:
            parts.pop(0)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts), "python"
    if suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
        parts = list(source.with_suffix("").parts)
        if parts and parts[-1] == "index":
            parts.pop()
        return "/".join(parts), "typescript" if suffix in {".ts", ".tsx"} else "javascript"
    if suffix == ".java":
        match = _JAVA_PACKAGE.search(content)
        package = match.group(1) if match else ""
        return f"{package}.{source.stem}".strip("."), "java"
    return str(source.with_suffix("")), "text"


def _parse_named_exports(body: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for item in body.strip().strip("{}").split(","):
        focused = item.strip()
        if not focused:
            continue
        focused = re.sub(r"^type\s+", "", focused)
        parts = re.split(r"\s+as\s+", focused, maxsplit=1)
        original = parts[0].strip()
        exported = parts[1].strip() if len(parts) == 2 else original
        if original and exported:
            result.append((original, exported))
    return result


@dataclass(frozen=True)
class ModuleIdentity:
    id: str
    repository: str
    ref: str
    tree_sha: str
    path: str
    file_sha: str
    language: str
    module_name: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        snapshot: dict[str, Any],
        *,
        path: str,
        file_sha: str,
        language: str,
        module_name: str,
    ) -> ModuleIdentity:
        fields = (
            str(snapshot.get("repository") or ""),
            str(snapshot.get("ref") or ""),
            str(snapshot.get("tree_sha") or ""),
            path,
            file_sha,
            language,
            module_name,
        )
        digest = hashlib.sha256("\x1f".join(fields).encode("utf-8")).hexdigest()[:24]
        return cls(
            id=f"module_{digest}",
            repository=fields[0],
            ref=fields[1],
            tree_sha=fields[2],
            path=fields[3],
            file_sha=fields[4],
            language=fields[5],
            module_name=fields[6],
        )


@dataclass(frozen=True)
class ExportEdge:
    source_module_id: str
    source_path: str
    target_module_id: str
    target_path: str
    imported_name: str
    exported_name: str
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OverloadGroup:
    id: str
    module_id: str
    parent: str
    name: str
    kind: str
    symbol_ids: tuple[str, ...]
    signatures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModuleGraph:
    def __init__(self, graph: RepositoryGraphIndex) -> None:
        self.graph = graph
        self.snapshot = graph.snapshot
        self.paths = set(graph.raw_files)
        self.aliases = load_module_aliases(self.snapshot)
        self.modules_by_path: dict[str, ModuleIdentity] = {}
        self.modules_by_id: dict[str, ModuleIdentity] = {}
        for path, raw in graph.raw_files.items():
            if PurePosixPath(path).suffix.lower() not in _SOURCE_SUFFIXES:
                continue
            module_name, language = _module_name(path, str(raw.get("content") or ""))
            identity = ModuleIdentity.create(
                self.snapshot,
                path=path,
                file_sha=str(raw.get("sha") or ""),
                language=language,
                module_name=module_name,
            )
            self.modules_by_path[path] = identity
            self.modules_by_id[identity.id] = identity
        self.exports = self._collect_exports()
        self.exports_by_source: dict[str, list[ExportEdge]] = defaultdict(list)
        for edge in self.exports:
            self.exports_by_source[edge.source_path].append(edge)
        self.symbols_by_path_name: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for symbol in graph.symbols:
            evidence = symbol.get("evidence", {})
            path = str(evidence.get("path") or "")
            self.symbols_by_path_name[(path, str(symbol.get("name") or ""))].append(symbol)
        self.overload_groups = self._build_overload_groups()

    def _resolve_target(self, source_path: str, module: str) -> str:
        return resolve_snapshot_import(source_path, module, self.paths, self.aliases)

    def _edge(
        self,
        source_path: str,
        target_path: str,
        imported_name: str,
        exported_name: str,
        kind: str,
    ) -> ExportEdge | None:
        source = self.modules_by_path.get(source_path)
        target = self.modules_by_path.get(target_path)
        if source is None or target is None:
            return None
        return ExportEdge(
            source_module_id=source.id,
            source_path=source_path,
            target_module_id=target.id,
            target_path=target_path,
            imported_name=imported_name,
            exported_name=exported_name,
            kind=kind,
        )

    def _collect_exports(self) -> tuple[ExportEdge, ...]:
        edges: list[ExportEdge] = []
        for path, raw in self.graph.raw_files.items():
            content = str(raw.get("content") or "")
            suffix = PurePosixPath(path).suffix.lower()
            if suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
                for match in _TS_EXPORT_FROM.finditer(content):
                    target_path = self._resolve_target(path, match.group("module"))
                    if not target_path:
                        continue
                    body = match.group("body")
                    if body == "*":
                        edge = self._edge(path, target_path, "*", "*", "export_all")
                        if edge:
                            edges.append(edge)
                    else:
                        for imported, exported in _parse_named_exports(body):
                            edge = self._edge(path, target_path, imported, exported, "re_export")
                            if edge:
                                edges.append(edge)
            if suffix == ".py" and PurePosixPath(path).name == "__init__.py":
                for match in _PYTHON_FROM_IMPORT.finditer(content):
                    target_path = self._resolve_target(path, match.group("module"))
                    if not target_path:
                        continue
                    for imported, exported in _parse_named_exports(match.group("body")):
                        edge = self._edge(path, target_path, imported, exported, "python_re_export")
                        if edge:
                            edges.append(edge)
        unique = {
            (
                edge.source_path,
                edge.target_path,
                edge.imported_name,
                edge.exported_name,
                edge.kind,
            ): edge
            for edge in edges
        }
        return tuple(unique[key] for key in sorted(unique))

    def _build_overload_groups(self) -> tuple[OverloadGroup, ...]:
        buckets: dict[tuple[str, str, str, str], list[tuple[str, str]]] = defaultdict(list)
        for symbol in self.graph.symbols:
            evidence = symbol.get("evidence", {})
            path = str(evidence.get("path") or "")
            module = self.modules_by_path.get(path)
            if module is None:
                continue
            identity = SymbolIdentity.from_symbol(self.snapshot, symbol)
            key = (
                module.id,
                str(symbol.get("parent") or ""),
                str(symbol.get("name") or ""),
                str(symbol.get("kind") or ""),
            )
            buckets[key].append((identity.id, str(symbol.get("signature") or "")))
        groups: list[OverloadGroup] = []
        for (module_id, parent, name, kind), members in sorted(buckets.items()):
            signatures = tuple(signature for _, signature in members)
            if len(members) < 2 or len(set(signatures)) < 2:
                continue
            digest = hashlib.sha256(
                "\x1f".join((module_id, parent, name, kind)).encode("utf-8")
            ).hexdigest()[:24]
            groups.append(
                OverloadGroup(
                    id=f"overload_{digest}",
                    module_id=module_id,
                    parent=parent,
                    name=name,
                    kind=kind,
                    symbol_ids=tuple(symbol_id for symbol_id, _ in members),
                    signatures=signatures,
                )
            )
        return tuple(groups)

    def module_for_path(self, path: str) -> ModuleIdentity | None:
        return self.modules_by_path.get(_normalized_path(path))

    def resolve_export(self, source_path: str, exported_name: str) -> dict[str, Any]:
        queue: list[tuple[str, str, tuple[str, ...]]] = [(source_path, exported_name, ())]
        visited: set[tuple[str, str]] = set()
        candidates: list[dict[str, Any]] = []
        while queue:
            path, name, chain = queue.pop(0)
            key = (path, name)
            if key in visited or len(chain) >= 12:
                continue
            visited.add(key)
            for symbol in self.symbols_by_path_name.get((path, name), []):
                candidates.append({"symbol": symbol, "export_chain": list(chain)})
            for edge in self.exports_by_source.get(path, []):
                if edge.exported_name not in {name, "*"}:
                    continue
                next_name = name if edge.imported_name == "*" else edge.imported_name
                queue.append((edge.target_path, next_name, (*chain, edge.source_path)))
        unique: dict[tuple[str, int, str], dict[str, Any]] = {}
        for item in candidates:
            symbol = item["symbol"]
            evidence = symbol.get("evidence", {})
            key = (
                str(evidence.get("path") or ""),
                int(evidence.get("start_line") or 0),
                str(symbol.get("qualified_name") or ""),
            )
            unique[key] = item
        payload = list(unique.values())
        return {
            "status": "resolved" if len(payload) == 1 else ("ambiguous" if payload else "unresolved"),
            "source_path": source_path,
            "exported_name": exported_name,
            "candidates": payload,
        }

    def stats(self) -> dict[str, int]:
        return {
            "module_count": len(self.modules_by_path),
            "export_edge_count": len(self.exports),
            "overload_group_count": len(self.overload_groups),
        }


class ModuleSemanticIndex:
    """Enriches semantic impact analysis with module and export identities."""

    def __init__(self, graph: RepositoryGraphIndex) -> None:
        self.graph = graph
        self.base = SemanticImpactIndex(graph)
        self.modules = ModuleGraph(graph)
        self._repair_reexport_calls()

    def _repair_reexport_calls(self) -> None:
        imports_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in self.graph.imports:
            imports_by_source[str(edge.get("evidence", {}).get("path") or "")].append(edge)
        repaired: list[dict[str, Any]] = []
        for edge in self.base.calls:
            if edge.get("resolution_status") == "resolved":
                repaired.append(edge)
                continue
            source_path = str(edge.get("source_path") or "")
            callee_name = _terminal(str(edge.get("callee") or ""))
            resolutions: list[dict[str, Any]] = []
            for imported in imports_by_source.get(source_path, []):
                names = {str(name) for name in imported.get("names", [])}
                if names and callee_name not in names and "*" not in names:
                    continue
                barrel = str(imported.get("resolved_path") or "")
                if barrel:
                    resolutions.append(self.modules.resolve_export(barrel, callee_name))
            candidates = [
                item
                for resolution in resolutions
                for item in resolution.get("candidates", [])
                if isinstance(item, dict)
            ]
            if len(candidates) != 1:
                repaired.append(
                    {
                        **edge,
                        "module_resolution": {
                            "status": "ambiguous" if candidates else "unresolved",
                            "candidates": candidates,
                        },
                    }
                )
                continue
            symbol = candidates[0]["symbol"]
            identity = SymbolIdentity.from_symbol(self.graph.snapshot, symbol)
            repaired.append(
                {
                    **edge,
                    "resolved_symbol": str(symbol.get("qualified_name") or symbol.get("name") or ""),
                    "resolved_path": identity.path,
                    "target_evidence": symbol.get("evidence"),
                    "target_symbol_id": identity.id,
                    "resolution_status": "resolved",
                    "module_resolution": {
                        "status": "resolved",
                        "export_chain": candidates[0].get("export_chain", []),
                    },
                }
            )
        self.base.calls = repaired

    def _enrich_symbol(self, item: dict[str, Any]) -> dict[str, Any]:
        evidence = item.get("evidence", {})
        path = str(evidence.get("path") or "")
        module = self.modules.module_for_path(path)
        identity = item.get("symbol_identity")
        if not isinstance(identity, dict):
            identity = SymbolIdentity.from_symbol(self.graph.snapshot, item).to_dict()
        overload_group = next(
            (
                group
                for group in self.modules.overload_groups
                if str(identity.get("id") or "") in group.symbol_ids
            ),
            None,
        )
        module_qualified = (
            f"{module.module_name}.{item.get('qualified_name') or item.get('name') or ''}"
            if module and module.module_name
            else str(item.get("qualified_name") or item.get("name") or "")
        )
        return {
            **item,
            "symbol_identity": identity,
            "module_identity": module.to_dict() if module else None,
            "module_qualified_name": module_qualified,
            "overload_group_id": overload_group.id if overload_group else "",
        }

    def inspect(self, symbol: str, *, top_k: int = 20) -> dict[str, Any]:
        result = self.base.inspect(symbol, top_k=top_k)
        definitions = [self._enrich_symbol(dict(item)) for item in result.get("definitions", [])]
        resolution = dict(result.get("resolution") or {})
        if isinstance(resolution.get("selected"), dict):
            resolution["selected"] = self._enrich_symbol(dict(resolution["selected"]))
        resolution["candidates"] = [
            self._enrich_symbol(dict(item))
            for item in resolution.get("candidates", [])
            if isinstance(item, dict)
        ]
        return {
            **result,
            "definitions": definitions,
            "resolution": resolution,
            "modules": [module.to_dict() for module in self.modules.modules_by_path.values()],
            "exports": [edge.to_dict() for edge in self.modules.exports],
            "overload_groups": [group.to_dict() for group in self.modules.overload_groups],
            "stats": {**dict(result.get("stats") or {}), **self.modules.stats()},
        }

    def impact(self, symbol: str, **kwargs: Any) -> dict[str, Any]:
        result = self.base.impact(symbol, **kwargs)
        return {
            **result,
            "module_stats": self.modules.stats(),
            "overload_groups": [group.to_dict() for group in self.modules.overload_groups],
        }
