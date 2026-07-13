"""Repository graph queries layered over durable GitHub snapshots."""

from __future__ import annotations

from typing import Any
from weakref import WeakKeyDictionary

from src.application.github_snapshot_service import GitHubSnapshotService
from src.web.advanced_module_semantics import AdvancedModuleSemanticIndex
from src.web.evidence_pinning import pin_evidence_refs
from src.web.lsp_adapter import LspAdapter, NullLspAdapter
from src.web.repository_graph import RepositoryGraphIndex


def _focused(value: str) -> str:
    return " ".join(str(value or "").split())


def _index_key(snapshot: dict[str, Any]) -> str:
    run_id = str(snapshot.get("snapshot_run_id") or "")
    tree_sha = str(snapshot.get("tree_sha") or "")
    commit_sha = str(snapshot.get("commit_sha") or "")
    files = ",".join(
        f"{item.get('path', '')}:{item.get('sha', '')}"
        for item in snapshot.get("files", [])
        if isinstance(item, dict)
    )
    return f"{run_id}:{commit_sha}:{tree_sha}:{files}"


def _ensure_root_file(
    result: dict[str, Any],
    *,
    max_files: int,
) -> dict[str, Any]:
    resolution = result.get("resolution")
    if not isinstance(resolution, dict):
        return result
    selected = resolution.get("selected")
    if not isinstance(selected, dict):
        return result
    identity = selected.get("symbol_identity")
    if not isinstance(identity, dict):
        return result
    path = str(identity.get("path") or "")
    if not path:
        return result
    files = [dict(item) for item in result.get("files", []) if isinstance(item, dict)]
    existing = next((item for item in files if item.get("path") == path), None)
    inserted = existing is None
    if existing is not None:
        reasons = {str(reason) for reason in existing.get("reasons", [])}
        reasons.add("root")
        existing["reasons"] = sorted(reasons)
        files.remove(existing)
        files.insert(0, existing)
    else:
        files.insert(
            0,
            {
                "path": path,
                "file_sha": str(identity.get("file_sha") or ""),
                "reasons": ["root"],
            },
        )
    bounded_files = max(1, min(max_files, 100))
    trimmed = len(files) > bounded_files
    files = files[:bounded_files]
    return {
        **result,
        "files": files,
        "truncated": bool(result.get("truncated")) or trimmed or inserted and trimmed,
        "stats": {
            **dict(result.get("stats") or {}),
            "file_count": len(files),
        },
    }


class GitHubGraphService:
    def __init__(
        self,
        snapshot_service: GitHubSnapshotService,
        *,
        lsp_adapter: LspAdapter | None = None,
    ) -> None:
        self.snapshot_service = snapshot_service
        self.lsp_adapter = lsp_adapter or NullLspAdapter()
        self._indexes: dict[str, RepositoryGraphIndex] = {}
        self._semantic_indexes: dict[str, AdvancedModuleSemanticIndex] = {}

    def _index(self, snapshot: dict[str, Any]) -> RepositoryGraphIndex:
        key = _index_key(snapshot)
        index = self._indexes.get(key)
        if index is None:
            index = RepositoryGraphIndex(snapshot)
            self._indexes[key] = index
        return index

    def _semantic_index(self, snapshot: dict[str, Any]) -> AdvancedModuleSemanticIndex:
        key = _index_key(snapshot)
        index = self._semantic_indexes.get(key)
        if index is None:
            index = AdvancedModuleSemanticIndex(self._index(snapshot))
            self._semantic_indexes[key] = index
        return index

    def _snapshot(
        self,
        repo_url: str,
        query: str,
        *,
        ref: str = "",
    ) -> dict[str, Any]:
        return self.snapshot_service.snapshot(repo_url, query=query, ref=ref)

    def _lsp_payload(self, inspected: dict[str, Any]) -> dict[str, Any]:
        resolution = inspected.get("resolution")
        if not isinstance(resolution, dict):
            return {"status": "not_applicable", "provider": self.lsp_adapter.provider}
        selected = resolution.get("selected")
        if not isinstance(selected, dict):
            return {
                "status": "not_applicable",
                "provider": self.lsp_adapter.provider,
                "reason": str(resolution.get("status") or "unresolved"),
            }
        evidence = selected.get("evidence")
        if not isinstance(evidence, dict):
            return {"status": "not_applicable", "provider": self.lsp_adapter.provider}
        path = str(evidence.get("path") or "")
        line = max(0, int(evidence.get("start_line") or 1) - 1)
        if not path:
            return {"status": "not_applicable", "provider": self.lsp_adapter.provider}
        definition = self.lsp_adapter.definition(path, line, 0)
        references = self.lsp_adapter.references(path, line, 0)
        type_info = self.lsp_adapter.type_info(path, line, 0)
        return {
            "status": (
                "available"
                if any(
                    item.status not in {"unavailable", "failed"}
                    for item in (definition, references, type_info)
                )
                else "unavailable"
            ),
            "provider": self.lsp_adapter.provider,
            "definition": definition.to_dict(),
            "references": references.to_dict(),
            "type_info": type_info.to_dict(),
        }

    def inspect(
        self,
        repo_url: str,
        symbol: str,
        *,
        ref: str = "",
        top_k: int = 20,
    ) -> dict[str, Any]:
        focused_symbol = _focused(symbol)
        if not focused_symbol:
            return {
                "ok": False,
                "error": "empty_symbol",
                "symbol": focused_symbol,
            }
        snapshot = self._snapshot(repo_url, focused_symbol, ref=ref)
        if snapshot.get("ok") is not True:
            return {**snapshot, "symbol": focused_symbol}
        inspected = self._semantic_index(snapshot).inspect(
            focused_symbol,
            top_k=max(1, min(top_k, 50)),
        )
        inspected = pin_evidence_refs(inspected, snapshot)
        return {
            **inspected,
            "requested_ref": str(snapshot.get("requested_ref") or snapshot.get("ref") or ""),
            "commit_sha": str(snapshot.get("commit_sha") or ""),
            "lsp": self._lsp_payload(inspected),
            "snapshot_run_id": str(snapshot.get("snapshot_run_id") or ""),
            "cache_hit": bool(snapshot.get("cache_hit")),
            "cache_mode": str(snapshot.get("cache_mode") or ""),
        }

    def impact(
        self,
        repo_url: str,
        symbol: str,
        *,
        ref: str = "",
        depth: int = 2,
        max_files: int = 30,
        max_edges: int = 120,
    ) -> dict[str, Any]:
        focused_symbol = _focused(symbol)
        if not focused_symbol:
            return {
                "ok": False,
                "error": "empty_symbol",
                "symbol": focused_symbol,
            }
        snapshot = self._snapshot(repo_url, focused_symbol, ref=ref)
        if snapshot.get("ok") is not True:
            return {**snapshot, "symbol": focused_symbol}
        bounded_files = max(1, min(max_files, 100))
        result = self._semantic_index(snapshot).impact(
            focused_symbol,
            depth=max(1, min(depth, 4)),
            max_files=bounded_files,
            max_edges=max(1, min(max_edges, 500)),
        )
        result = _ensure_root_file(result, max_files=bounded_files)
        result = pin_evidence_refs(result, snapshot)
        return {
            **result,
            "requested_ref": str(snapshot.get("requested_ref") or snapshot.get("ref") or ""),
            "commit_sha": str(snapshot.get("commit_sha") or ""),
            "snapshot_run_id": str(snapshot.get("snapshot_run_id") or ""),
            "cache_hit": bool(snapshot.get("cache_hit")),
            "cache_mode": str(snapshot.get("cache_mode") or ""),
        }


_services: WeakKeyDictionary[GitHubSnapshotService, GitHubGraphService] = (
    WeakKeyDictionary()
)


def graph_service_for(snapshot_service: GitHubSnapshotService) -> GitHubGraphService:
    service = _services.get(snapshot_service)
    if service is None:
        service = GitHubGraphService(snapshot_service)
        _services[snapshot_service] = service
    return service
