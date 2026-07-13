"""Tree-sitter enriched repository graph over a persisted GitHub snapshot."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from src.web.github_structure import RepositoryStructureIndex, evidence_for_range
from src.web.module_aliases import load_module_aliases, resolve_snapshot_import
from src.web.tree_sitter_backend import parse_with_tree_sitter


def _variants(value: str) -> set[str]:
    focused = value.strip()
    if not focused:
        return set()
    terminal = focused.rsplit(".", 1)[-1]
    return {
        focused.casefold(),
        terminal.casefold(),
        focused.replace("_", "").casefold(),
        terminal.replace("_", "").casefold(),
    }


def _matches(value: str, variants: set[str]) -> bool:
    return bool(_variants(value) & variants)


class RepositoryGraphIndex:
    """Adds call/inheritance graphs while retaining the legacy fallback index."""

    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = dict(snapshot)
        self.legacy = RepositoryStructureIndex(snapshot)
        self.files = self.legacy.files
        self.raw_files = self.legacy.raw_files
        self.aliases = load_module_aliases(snapshot)
        self.parsed: dict[str, Any] = {}
        self.symbols: list[dict[str, Any]] = []
        self.imports: list[dict[str, Any]] = []
        raw_calls: list[dict[str, Any]] = []
        raw_inheritance: list[dict[str, Any]] = []
        paths = set(self.raw_files)

        for path, raw_file in self.raw_files.items():
            parsed = parse_with_tree_sitter(path, str(raw_file.get("content") or ""))
            if parsed is None:
                continue
            self.parsed[path] = parsed
            for symbol in parsed.symbols:
                self.symbols.append(
                    {
                        "name": symbol.name,
                        "qualified_name": symbol.qualified_name,
                        "kind": symbol.kind,
                        "language": parsed.language,
                        "signature": symbol.signature,
                        "parent": symbol.parent,
                        "parser": parsed.parser,
                        "evidence": self._evidence(
                            path,
                            raw_file,
                            symbol.start_line,
                            symbol.end_line,
                            symbol.qualified_name,
                            "definition",
                        ),
                    }
                )
            for edge in parsed.imports:
                self.imports.append(
                    {
                        "module": edge.module,
                        "names": list(edge.names),
                        "kind": edge.kind,
                        "resolved_path": resolve_snapshot_import(
                            path,
                            edge.module,
                            paths,
                            self.aliases,
                        ),
                        "evidence": self._evidence(
                            path,
                            raw_file,
                            edge.start_line,
                            edge.end_line,
                            "",
                            "import",
                        ),
                    }
                )
            for edge in parsed.calls:
                raw_calls.append(
                    {
                        "caller": edge.caller,
                        "callee": edge.callee,
                        "kind": edge.kind,
                        "source_path": path,
                        "evidence": self._evidence(
                            path,
                            raw_file,
                            edge.start_line,
                            edge.end_line,
                            edge.callee,
                            "call",
                        ),
                    }
                )
            for edge in parsed.inheritance:
                raw_inheritance.append(
                    {
                        "child": edge.child,
                        "parent": edge.parent,
                        "kind": edge.kind,
                        "source_path": path,
                        "evidence": self._evidence(
                            path,
                            raw_file,
                            edge.start_line,
                            edge.end_line,
                            edge.child,
                            "inheritance",
                        ),
                    }
                )
        self._symbols_by_name = self._symbol_index()
        self.calls = [self._resolve_call(edge) for edge in raw_calls]
        self.inheritance = [
            self._resolve_inheritance(edge) for edge in raw_inheritance
        ]

    def _evidence(
        self,
        path: str,
        raw_file: dict[str, Any],
        start: int,
        end: int,
        symbol: str,
        kind: str,
    ) -> dict[str, Any]:
        return evidence_for_range(
            self.snapshot,
            path=path,
            file_sha=str(raw_file.get("sha") or ""),
            start_line=start,
            end_line=end,
            symbol=symbol,
            kind=kind,
        )

    def _symbol_index(self) -> dict[str, list[dict[str, Any]]]:
        index: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for symbol in self.symbols:
            for key in _variants(str(symbol.get("name") or "")) | _variants(
                str(symbol.get("qualified_name") or "")
            ):
                index[key].append(symbol)
        return dict(index)

    def _candidate_symbols(self, value: str) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        seen: set[tuple[str, int, str]] = set()
        for key in _variants(value):
            for item in self._symbols_by_name.get(key, []):
                evidence = item.get("evidence", {})
                identity = (
                    str(evidence.get("path") or ""),
                    int(evidence.get("start_line") or 0),
                    str(item.get("qualified_name") or ""),
                )
                if identity not in seen:
                    seen.add(identity)
                    candidates.append(item)
        return candidates

    def _resolve_symbol(self, value: str, source_path: str) -> dict[str, Any] | None:
        candidates = self._candidate_symbols(value)
        if not candidates:
            return None
        same_file = [
            item
            for item in candidates
            if item.get("evidence", {}).get("path") == source_path
        ]
        if len(same_file) == 1:
            return same_file[0]
        imported_paths = {
            str(edge.get("resolved_path") or "")
            for edge in self.imports
            if edge.get("evidence", {}).get("path") == source_path
        }
        imported = [
            item
            for item in candidates
            if item.get("evidence", {}).get("path") in imported_paths
        ]
        if len(imported) == 1:
            return imported[0]
        return candidates[0] if len(candidates) == 1 else None

    def _resolve_call(self, edge: dict[str, Any]) -> dict[str, Any]:
        target = self._resolve_symbol(
            str(edge.get("callee") or ""),
            str(edge.get("source_path") or ""),
        )
        return {
            **edge,
            "resolved_symbol": str(target.get("qualified_name") or "") if target else "",
            "resolved_path": (
                str(target.get("evidence", {}).get("path") or "") if target else ""
            ),
            "target_evidence": target.get("evidence") if target else None,
        }

    def _resolve_inheritance(self, edge: dict[str, Any]) -> dict[str, Any]:
        target = self._resolve_symbol(
            str(edge.get("parent") or ""),
            str(edge.get("source_path") or ""),
        )
        return {
            **edge,
            "resolved_parent": str(target.get("qualified_name") or "") if target else "",
            "resolved_path": (
                str(target.get("evidence", {}).get("path") or "") if target else ""
            ),
            "target_evidence": target.get("evidence") if target else None,
        }

    def definitions(self, symbol: str, *, top_k: int = 20) -> list[dict[str, Any]]:
        variants = _variants(symbol)
        ranked: list[tuple[int, dict[str, Any]]] = []
        for item in self.symbols:
            qualified = str(item.get("qualified_name") or "")
            name = str(item.get("name") or "")
            if qualified.casefold() in variants or name.casefold() in variants:
                score = 110
            elif _matches(name, variants) or _matches(qualified, variants):
                score = 100
            else:
                continue
            ranked.append((score, item))
        legacy = self.legacy.definitions(symbol, top_k=top_k)
        for item in legacy:
            ranked.append((int(item.get("score") or 0), item))
        ranked.sort(
            key=lambda row: (
                -row[0],
                str(row[1].get("evidence", {}).get("path") or ""),
                int(row[1].get("evidence", {}).get("start_line") or 0),
            )
        )
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, int, str]] = set()
        for score, item in ranked:
            evidence = item.get("evidence", {})
            identity = (
                str(evidence.get("path") or ""),
                int(evidence.get("start_line") or 0),
                str(item.get("qualified_name") or item.get("name") or ""),
            )
            if identity in seen:
                continue
            seen.add(identity)
            result.append({**item, "score": score, "rank": len(result) + 1})
            if len(result) >= max(1, min(top_k, 100)):
                break
        return result

    def references(self, symbol: str, *, top_k: int = 50) -> list[dict[str, Any]]:
        return self.legacy.references(symbol, top_k=top_k)

    def callers(self, symbol: str, *, top_k: int = 50) -> list[dict[str, Any]]:
        variants = _variants(symbol)
        result = [
            edge
            for edge in self.calls
            if _matches(str(edge.get("callee") or ""), variants)
            or _matches(str(edge.get("resolved_symbol") or ""), variants)
        ]
        return result[: max(1, min(top_k, 200))]

    def callees(self, symbol: str, *, top_k: int = 50) -> list[dict[str, Any]]:
        variants = _variants(symbol)
        result = [
            edge
            for edge in self.calls
            if _matches(str(edge.get("caller") or ""), variants)
        ]
        return result[: max(1, min(top_k, 200))]

    def hierarchy(self, symbol: str, *, top_k: int = 50) -> list[dict[str, Any]]:
        variants = _variants(symbol)
        result = [
            edge
            for edge in self.inheritance
            if _matches(str(edge.get("child") or ""), variants)
            or _matches(str(edge.get("parent") or ""), variants)
            or _matches(str(edge.get("resolved_parent") or ""), variants)
        ]
        return result[: max(1, min(top_k, 200))]

    def related_files(self, symbol: str, *, top_k: int = 20) -> list[dict[str, Any]]:
        paths: dict[str, set[str]] = defaultdict(set)
        for item in self.legacy.related_files(symbol, top_k=top_k * 2):
            path = str(item.get("path") or "")
            paths[path].update(str(reason) for reason in item.get("reasons", []))
        for edge in [*self.callers(symbol), *self.callees(symbol), *self.hierarchy(symbol)]:
            source = str(edge.get("source_path") or "")
            target = str(edge.get("resolved_path") or "")
            if source:
                paths[source].add(str(edge.get("kind") or "graph"))
            if target:
                paths[target].add("graph_target")
        result = []
        for path in sorted(paths):
            raw = self.raw_files.get(path, {})
            parsed = self.parsed.get(path)
            fallback = self.files.get(path)
            result.append(
                {
                    "path": path,
                    "reasons": sorted(paths[path]),
                    "language": (
                        parsed.language
                        if parsed is not None
                        else (fallback.language if fallback is not None else "text")
                    ),
                    "file_sha": str(raw.get("sha") or ""),
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
            "callers": self.callers(symbol, top_k=top_k * 3),
            "callees": self.callees(symbol, top_k=top_k * 3),
            "hierarchy": self.hierarchy(symbol, top_k=top_k * 3),
            "related_files": self.related_files(symbol, top_k=top_k),
            "stats": self.stats(),
        }

    def stats(self) -> dict[str, Any]:
        parser_counts = Counter(parsed.parser for parsed in self.parsed.values())
        legacy_stats = self.legacy.stats()
        return {
            **legacy_stats,
            "parser": "tree_sitter+legacy_fallback",
            "tree_sitter_file_count": len(self.parsed),
            "fallback_file_count": len(self.files) - len(self.parsed),
            "call_count": len(self.calls),
            "resolved_call_count": sum(
                bool(edge.get("resolved_path")) for edge in self.calls
            ),
            "inheritance_count": len(self.inheritance),
            "resolved_inheritance_count": sum(
                bool(edge.get("resolved_path")) for edge in self.inheritance
            ),
            "module_alias_count": len(self.aliases),
            "parser_counts": dict(sorted(parser_counts.items())),
            "tree_sitter_parse_error_count": sum(
                bool(parsed.parse_error) for parsed in self.parsed.values()
            ),
        }
