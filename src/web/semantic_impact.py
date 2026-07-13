"""Semantic symbol resolution and bounded impact analysis over repository graphs."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
import hashlib
import re
from typing import Any

from src.web.github_structure import evidence_for_range
from src.web.repository_graph import RepositoryGraphIndex


_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__)(/|$)|(^|/)(test_[^/]+|[^/]+_test)\.py$|"
    r"\.(test|spec)\.[cm]?[jt]sx?$|(^|/)[A-Za-z0-9_$]+Test\.java$",
    re.IGNORECASE,
)


def _terminal(value: str) -> str:
    return str(value or "").strip().rsplit(".", 1)[-1]


def _normalized(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_$]", "", str(value or "")).casefold()


def _variants(value: str) -> set[str]:
    focused = str(value or "").strip()
    terminal = _terminal(focused)
    return {
        item
        for item in {
            focused.casefold(),
            terminal.casefold(),
            _normalized(focused),
            _normalized(terminal),
        }
        if item
    }


def _parameter_count(signature: str) -> int | None:
    text = str(signature or "")
    if "(" not in text or ")" not in text:
        return None
    payload = text.split("(", 1)[1].rsplit(")", 1)[0].strip()
    if not payload:
        return 0
    depth = 0
    count = 1
    for character in payload:
        if character in "[(<{":
            depth += 1
        elif character in "])}>" and depth:
            depth -= 1
        elif character == "," and depth == 0:
            count += 1
    return count


def _receiver(value: str) -> str:
    focused = str(value or "").strip()
    if "." not in focused:
        return ""
    return focused.rsplit(".", 1)[0]


def _type_hints(content: str) -> dict[str, str]:
    """Extract conservative receiver-to-type hints without claiming full typing."""

    result: dict[str, str] = {}
    text = str(content or "")

    # Python/TypeScript annotations and Java fields/parameters.
    for name, type_name in re.findall(
        r"\b(?:self\.|this\.)?([A-Za-z_$][A-Za-z0-9_$]*)\s*:\s*"
        r"([A-Za-z_$][A-Za-z0-9_$.<>\[\]?]*)",
        text,
    ):
        result[name] = _terminal(type_name.split("<", 1)[0].rstrip("[]?"))
    for type_name, name in re.findall(
        r"\b([A-Z][A-Za-z0-9_$.]*(?:<[^;=(){}]+>)?)\s+"
        r"([a-z_$][A-Za-z0-9_$]*)\b",
        text,
    ):
        result[name] = _terminal(type_name.split("<", 1)[0])

    # Direct constructor assignments.
    for receiver, type_name in re.findall(
        r"\b((?:self|this)\.[A-Za-z_$][A-Za-z0-9_$]*|"
        r"[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*new\s+"
        r"([A-Za-z_$][A-Za-z0-9_$.]*)",
        text,
    ):
        result[receiver] = _terminal(type_name)
        result[_terminal(receiver)] = _terminal(type_name)
    for receiver, type_name in re.findall(
        r"\b((?:self|this)\.[A-Za-z_$][A-Za-z0-9_$]*|"
        r"[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
        r"([A-Z][A-Za-z0-9_$.]*)\s*\(",
        text,
    ):
        result[receiver] = _terminal(type_name)
        result[_terminal(receiver)] = _terminal(type_name)

    # Constructor injection: parameter type plus self/this assignment.
    parameter_types = dict(
        re.findall(
            r"\b([A-Za-z_$][A-Za-z0-9_$]*)\s*:\s*"
            r"([A-Z][A-Za-z0-9_$.]*)",
            text,
        )
    )
    for target, source in re.findall(
        r"\b((?:self|this)\.[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
        r"([A-Za-z_$][A-Za-z0-9_$]*)\b",
        text,
    ):
        inferred = parameter_types.get(source) or result.get(source)
        if inferred:
            result[target] = _terminal(inferred)
            result[_terminal(target)] = _terminal(inferred)
    return result


@dataclass(frozen=True)
class SymbolIdentity:
    id: str
    repository: str
    ref: str
    tree_sha: str
    path: str
    file_sha: str
    language: str
    kind: str
    qualified_name: str
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_symbol(
        cls,
        snapshot: dict[str, Any],
        symbol: dict[str, Any],
    ) -> SymbolIdentity:
        evidence = symbol.get("evidence", {})
        fields = (
            str(snapshot.get("repository") or ""),
            str(snapshot.get("ref") or ""),
            str(snapshot.get("tree_sha") or ""),
            str(evidence.get("path") or ""),
            str(evidence.get("file_sha") or ""),
            str(symbol.get("language") or ""),
            str(symbol.get("kind") or ""),
            str(symbol.get("qualified_name") or symbol.get("name") or ""),
            str(symbol.get("signature") or ""),
        )
        digest = hashlib.sha256("\x1f".join(fields).encode("utf-8")).hexdigest()[:24]
        return cls(
            id=f"symbol_{digest}",
            repository=fields[0],
            ref=fields[1],
            tree_sha=fields[2],
            path=fields[3],
            file_sha=fields[4],
            language=fields[5],
            kind=fields[6],
            qualified_name=fields[7],
            signature=fields[8],
        )


class SemanticImpactIndex:
    """Adds explainable symbol resolution, implementations, and bounded impact."""

    def __init__(self, graph: RepositoryGraphIndex) -> None:
        self.graph = graph
        self.snapshot = graph.snapshot
        self.identities: dict[str, SymbolIdentity] = {}
        self.symbol_by_id: dict[str, dict[str, Any]] = {}
        for symbol in graph.symbols:
            identity = SymbolIdentity.from_symbol(self.snapshot, symbol)
            self.identities[identity.id] = identity
            self.symbol_by_id[identity.id] = symbol
        self.type_hints = {
            path: _type_hints(str(raw.get("content") or ""))
            for path, raw in graph.raw_files.items()
        }
        self.calls = [self._resolve_call(edge) for edge in graph.calls]

    def _identity_for(self, symbol: dict[str, Any]) -> SymbolIdentity:
        candidate = SymbolIdentity.from_symbol(self.snapshot, symbol)
        return self.identities.get(candidate.id, candidate)

    def _candidate_symbols(self, query: str) -> list[dict[str, Any]]:
        variants = _variants(query)
        result = []
        for symbol in self.graph.symbols:
            if variants & (
                _variants(str(symbol.get("name") or ""))
                | _variants(str(symbol.get("qualified_name") or ""))
            ):
                result.append(symbol)
        return result

    def resolve(
        self,
        query: str,
        *,
        source_path: str = "",
        kind: str = "",
        signature: str = "",
        receiver: str = "",
        receiver_type: str = "",
        top_k: int = 10,
    ) -> dict[str, Any]:
        candidates = self._candidate_symbols(query)
        imported_paths = {
            str(edge.get("resolved_path") or "")
            for edge in self.graph.imports
            if edge.get("evidence", {}).get("path") == source_path
        }
        query_variants = _variants(query)
        requested_arity = _parameter_count(signature)
        ranked: list[tuple[int, list[str], dict[str, Any]]] = []
        for symbol in candidates:
            score = 0
            reasons: list[str] = []
            name = str(symbol.get("name") or "")
            qualified = str(symbol.get("qualified_name") or name)
            evidence = symbol.get("evidence", {})
            path = str(evidence.get("path") or "")
            parent = str(symbol.get("parent") or "")
            if qualified.casefold() == str(query or "").casefold():
                score += 130
                reasons.append("exact_qualified_name")
            elif name.casefold() == _terminal(query).casefold():
                score += 100
                reasons.append("exact_terminal_name")
            elif query_variants & _variants(qualified):
                score += 80
                reasons.append("normalized_name")
            if source_path and path == source_path:
                score += 28
                reasons.append("same_file")
            if path and path in imported_paths:
                score += 24
                reasons.append("imported_file")
            if kind and str(symbol.get("kind") or "") == kind:
                score += 18
                reasons.append("matching_kind")
            if receiver_type and _terminal(parent).casefold() == _terminal(receiver_type).casefold():
                score += 45
                reasons.append("receiver_type")
            elif receiver and _terminal(parent).casefold() == _terminal(receiver).casefold():
                score += 24
                reasons.append("receiver_name")
            candidate_arity = _parameter_count(str(symbol.get("signature") or ""))
            if requested_arity is not None and candidate_arity == requested_arity:
                score += 12
                reasons.append("matching_arity")
            ranked.append((score, reasons, symbol))
        ranked.sort(
            key=lambda row: (
                -row[0],
                str(row[2].get("evidence", {}).get("path") or ""),
                int(row[2].get("evidence", {}).get("start_line") or 0),
            )
        )
        limit = max(1, min(top_k, 50))
        payload = []
        for score, reasons, symbol in ranked[:limit]:
            identity = self._identity_for(symbol)
            payload.append(
                {
                    **symbol,
                    "symbol_identity": identity.to_dict(),
                    "semantic_score": score,
                    "semantic_reasons": reasons,
                }
            )
        if not payload:
            status = "unresolved"
            selected = None
        elif len(payload) == 1:
            status = "resolved"
            selected = payload[0]
        else:
            gap = int(payload[0]["semantic_score"]) - int(payload[1]["semantic_score"])
            exact = "exact_qualified_name" in payload[0]["semantic_reasons"]
            status = "resolved" if exact or gap >= 15 else "ambiguous"
            selected = payload[0] if status == "resolved" else None
        return {
            "status": status,
            "query": query,
            "source_path": source_path,
            "receiver": receiver,
            "receiver_type": receiver_type,
            "selected": selected,
            "candidates": payload,
            "candidate_count": len(candidates),
        }

    def _resolve_call(self, edge: dict[str, Any]) -> dict[str, Any]:
        source_path = str(edge.get("source_path") or "")
        callee = str(edge.get("callee") or "")
        receiver = _receiver(callee)
        hints = self.type_hints.get(source_path, {})
        receiver_type = hints.get(receiver) or hints.get(_terminal(receiver)) or ""
        resolution = self.resolve(
            _terminal(callee),
            source_path=source_path,
            kind="method" if receiver else "",
            receiver=receiver,
            receiver_type=receiver_type,
            top_k=8,
        )
        selected = resolution.get("selected")
        if not isinstance(selected, dict):
            return {
                **edge,
                "semantic_resolution": resolution,
                "resolution_status": str(resolution.get("status") or "unresolved"),
            }
        identity = selected.get("symbol_identity", {})
        evidence = selected.get("evidence")
        return {
            **edge,
            "resolved_symbol": str(selected.get("qualified_name") or selected.get("name") or ""),
            "resolved_path": str(identity.get("path") or ""),
            "target_evidence": evidence,
            "target_symbol_id": str(identity.get("id") or ""),
            "semantic_resolution": resolution,
            "resolution_status": "resolved",
        }

    def implementations(self, symbol: str, *, top_k: int = 50) -> list[dict[str, Any]]:
        resolution = self.resolve(symbol, top_k=top_k)
        roots = []
        selected = resolution.get("selected")
        if isinstance(selected, dict):
            roots = [selected]
        elif resolution.get("status") == "ambiguous":
            roots = list(resolution.get("candidates", []))[:3]
        root_names = {
            str(item.get("qualified_name") or item.get("name") or "")
            for item in roots
        }
        root_terminals = {_terminal(item) for item in root_names}
        results: list[dict[str, Any]] = []
        descendants: set[str] = set()
        for edge in self.graph.inheritance:
            parent = str(edge.get("resolved_parent") or edge.get("parent") or "")
            if _terminal(parent) not in root_terminals and parent not in root_names:
                continue
            child = str(edge.get("child") or "")
            descendants.add(_terminal(child))
            results.append({**edge, "implementation_kind": "class_or_interface"})
        method_name = _terminal(symbol)
        root_parents = {
            _terminal(str(item.get("parent") or ""))
            for item in roots
            if str(item.get("kind") or "") in {"method", "function"}
        }
        if root_parents:
            for edge in self.graph.inheritance:
                parent = _terminal(str(edge.get("resolved_parent") or edge.get("parent") or ""))
                if parent in root_parents:
                    descendants.add(_terminal(str(edge.get("child") or "")))
            for candidate in self.graph.symbols:
                if (
                    str(candidate.get("name") or "") == method_name
                    and _terminal(str(candidate.get("parent") or "")) in descendants
                ):
                    results.append(
                        {
                            "implementation_kind": "method_override",
                            "symbol": {
                                **candidate,
                                "symbol_identity": self._identity_for(candidate).to_dict(),
                            },
                        }
                    )
        return results[: max(1, min(top_k, 200))]

    def _symbol_for_qualified(self, value: str) -> dict[str, Any] | None:
        variants = _variants(value)
        candidates = [
            symbol
            for symbol in self.graph.symbols
            if variants & _variants(str(symbol.get("qualified_name") or symbol.get("name") or ""))
        ]
        return candidates[0] if len(candidates) == 1 else None

    def _test_files(
        self,
        symbol_names: set[str],
        impacted_paths: set[str],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        results = []
        terminals = {_terminal(name) for name in symbol_names if name}
        for path, raw in sorted(self.graph.raw_files.items()):
            if not _TEST_PATH.search(path):
                continue
            content = str(raw.get("content") or "")
            matched = sorted(
                name
                for name in terminals
                if re.search(rf"\b{re.escape(name)}\b", content)
            )
            imported_targets = sorted(
                {
                    str(edge.get("resolved_path") or "")
                    for edge in self.graph.imports
                    if edge.get("evidence", {}).get("path") == path
                    and str(edge.get("resolved_path") or "") in impacted_paths
                }
            )
            if not matched and not imported_targets:
                continue
            results.append(
                {
                    "path": path,
                    "file_sha": str(raw.get("sha") or ""),
                    "matched_symbols": matched,
                    "imported_impacted_paths": imported_targets,
                    "evidence": evidence_for_range(
                        self.snapshot,
                        path=path,
                        file_sha=str(raw.get("sha") or ""),
                        start_line=1,
                        end_line=max(1, len(content.splitlines())),
                        kind="test_file",
                    ),
                }
            )
            if len(results) >= limit:
                break
        return results

    def impact(
        self,
        symbol: str,
        *,
        depth: int = 2,
        max_files: int = 30,
        max_edges: int = 120,
    ) -> dict[str, Any]:
        bounded_depth = max(1, min(depth, 4))
        bounded_files = max(1, min(max_files, 100))
        bounded_edges = max(1, min(max_edges, 500))
        root_resolution = self.resolve(symbol, top_k=10)
        seeds = []
        selected = root_resolution.get("selected")
        if isinstance(selected, dict):
            seeds = [str(selected.get("qualified_name") or selected.get("name") or "")]
        elif root_resolution.get("status") == "ambiguous":
            seeds = [
                str(item.get("qualified_name") or item.get("name") or "")
                for item in root_resolution.get("candidates", [])[:3]
            ]
        queue = deque((seed, 0) for seed in seeds if seed)
        visited: set[str] = set()
        edges: list[dict[str, Any]] = []
        impacted_symbols: set[str] = set(seeds)
        file_reasons: dict[str, set[str]] = defaultdict(set)
        while queue and len(edges) < bounded_edges:
            current, current_depth = queue.popleft()
            key = current.casefold()
            if key in visited:
                continue
            visited.add(key)
            current_symbol = self._symbol_for_qualified(current)
            if current_symbol:
                path = str(current_symbol.get("evidence", {}).get("path") or "")
                if path:
                    file_reasons[path].add("root" if current_depth == 0 else "symbol")
            if current_depth >= bounded_depth:
                continue
            variants = _variants(current)
            for edge in self.calls:
                caller = str(edge.get("caller") or "")
                target = str(edge.get("resolved_symbol") or edge.get("callee") or "")
                if variants & _variants(caller):
                    edges.append({**edge, "impact_direction": "downstream"})
                    impacted_symbols.add(target)
                    queue.append((target, current_depth + 1))
                elif variants & _variants(target):
                    edges.append({**edge, "impact_direction": "upstream"})
                    impacted_symbols.add(caller)
                    queue.append((caller, current_depth + 1))
                else:
                    continue
                source_path = str(edge.get("source_path") or "")
                target_path = str(edge.get("resolved_path") or "")
                if source_path:
                    file_reasons[source_path].add(str(edges[-1]["impact_direction"]))
                if target_path:
                    file_reasons[target_path].add("call_target")
                if len(edges) >= bounded_edges:
                    break
            for relation in self.implementations(current, top_k=50):
                edges.append({**relation, "impact_direction": "implementation"})
                child = str(relation.get("child") or "")
                symbol_payload = relation.get("symbol")
                if isinstance(symbol_payload, dict):
                    child = str(
                        symbol_payload.get("qualified_name")
                        or symbol_payload.get("name")
                        or child
                    )
                if child:
                    impacted_symbols.add(child)
                    queue.append((child, current_depth + 1))
                source_path = str(relation.get("source_path") or "")
                if isinstance(symbol_payload, dict):
                    source_path = str(symbol_payload.get("evidence", {}).get("path") or source_path)
                if source_path:
                    file_reasons[source_path].add("implementation")
                if len(edges) >= bounded_edges:
                    break
        files = []
        for path in sorted(file_reasons)[:bounded_files]:
            raw = self.graph.raw_files.get(path, {})
            files.append(
                {
                    "path": path,
                    "file_sha": str(raw.get("sha") or ""),
                    "reasons": sorted(file_reasons[path]),
                }
            )
        impacted_paths = {item["path"] for item in files}
        tests = self._test_files(
            impacted_symbols,
            impacted_paths,
            limit=min(20, bounded_files),
        )
        return {
            "ok": True,
            "repository": str(self.snapshot.get("repository") or ""),
            "ref": str(self.snapshot.get("ref") or ""),
            "tree_sha": str(self.snapshot.get("tree_sha") or ""),
            "symbol": symbol,
            "resolution": root_resolution,
            "depth": bounded_depth,
            "symbols": sorted(impacted_symbols),
            "edges": edges[:bounded_edges],
            "files": files,
            "tests": tests,
            "truncated": len(edges) >= bounded_edges or len(file_reasons) > bounded_files,
            "stats": {
                "symbol_count": len(impacted_symbols),
                "edge_count": min(len(edges), bounded_edges),
                "file_count": len(files),
                "test_count": len(tests),
            },
        }

    def inspect(self, symbol: str, *, top_k: int = 20) -> dict[str, Any]:
        base = self.graph.inspect(symbol, top_k=top_k)
        resolution = self.resolve(symbol, top_k=top_k)
        return {
            **base,
            "resolution": resolution,
            "symbol_identities": [
                item.get("symbol_identity")
                for item in resolution.get("candidates", [])
                if isinstance(item, dict)
            ],
            "implementations": self.implementations(symbol, top_k=top_k * 2),
            "semantic_stats": {
                "identity_count": len(self.identities),
                "semantic_resolved_call_count": sum(
                    edge.get("resolution_status") == "resolved" for edge in self.calls
                ),
                "semantic_ambiguous_call_count": sum(
                    edge.get("resolution_status") == "ambiguous" for edge in self.calls
                ),
                "semantic_unresolved_call_count": sum(
                    edge.get("resolution_status") == "unresolved" for edge in self.calls
                ),
            },
        }
