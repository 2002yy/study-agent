"""Version-aware symbol and regression impact over commit-pinned GitHub snapshots."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import os
from pathlib import PurePosixPath
from typing import Any

from src.repositories.provider_cache_repository import (
    PROVIDER_CACHE_SCHEMA_VERSION,
    ProviderCacheRepository,
    provider_cache_key,
)
from src.web.advanced_module_semantics import AdvancedModuleSemanticIndex
from src.web.github_history import GitHubHistoryService
from src.web.repository_graph import RepositoryGraphIndex
from src.web.semantic_impact import SymbolIdentity

_SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java"}
_TEST_PARTS = {"test", "tests", "__tests__"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _source_path(path: str) -> bool:
    return PurePosixPath(str(path or "")).suffix.casefold() in _SOURCE_SUFFIXES


def _test_path(path: str) -> bool:
    source = PurePosixPath(str(path or ""))
    lowered = str(source).casefold()
    parts = {part.casefold() for part in source.parts}
    name = source.name.casefold()
    return bool(
        parts & _TEST_PARTS
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in lowered
        or ".spec." in lowered
        or name.endswith("test.java")
    )


def _ranges(file_change: dict[str, Any], side: str) -> list[tuple[int, int]]:
    prefix = "old" if side == "old" else "new"
    result: list[tuple[int, int]] = []
    for raw in file_change.get("hunks", []):
        if not isinstance(raw, dict):
            continue
        start = int(raw.get(f"{prefix}_start") or 0)
        end = int(raw.get(f"{prefix}_end") or start)
        if start > 0:
            result.append((start, max(start, end)))
    return result


def _overlaps(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= range_end and end >= range_start for range_start, range_end in ranges)


def _symbol_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("language") or "").casefold(),
        str(item.get("kind") or "").casefold(),
        str(item.get("qualified_name") or item.get("name") or "").casefold(),
    )


def _identity(snapshot: dict[str, Any], symbol: dict[str, Any]) -> dict[str, Any]:
    value = SymbolIdentity.from_symbol(snapshot, symbol).to_dict()
    value["commit_sha"] = str(snapshot.get("commit_sha") or snapshot.get("ref") or "")
    value["requested_ref"] = str(snapshot.get("requested_ref") or snapshot.get("ref") or "")
    return value


def _symbol_payload(
    snapshot: dict[str, Any],
    symbol: dict[str, Any],
    *,
    ranges: list[tuple[int, int]],
) -> dict[str, Any]:
    evidence = dict(symbol.get("evidence") or {})
    return {
        "name": str(symbol.get("name") or ""),
        "qualified_name": str(symbol.get("qualified_name") or symbol.get("name") or ""),
        "kind": str(symbol.get("kind") or ""),
        "language": str(symbol.get("language") or ""),
        "signature": str(symbol.get("signature") or ""),
        "parent": str(symbol.get("parent") or ""),
        "evidence": evidence,
        "identity": _identity(snapshot, symbol),
        "hunk_ranges": [
            {"start_line": start, "end_line": end} for start, end in ranges
        ],
    }


def _changed_symbols(
    graph: RepositoryGraphIndex | None,
    snapshot: dict[str, Any],
    *,
    path: str,
    ranges: list[tuple[int, int]],
    all_symbols: bool,
) -> list[dict[str, Any]]:
    if graph is None or not path:
        return []
    result: list[dict[str, Any]] = []
    for symbol in graph.symbols:
        evidence = symbol.get("evidence") if isinstance(symbol.get("evidence"), dict) else {}
        if str(evidence.get("path") or "") != path:
            continue
        start = int(evidence.get("start_line") or 1)
        end = int(evidence.get("end_line") or start)
        if not all_symbols and ranges and not _overlaps(start, end, ranges):
            continue
        result.append(_symbol_payload(snapshot, symbol, ranges=ranges))
    return result


def _change_id(
    base_sha: str,
    head_sha: str,
    change_type: str,
    old_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
) -> str:
    fields = [base_sha, head_sha, change_type]
    fields.extend(str(item.get("identity", {}).get("id") or "") for item in old_items)
    fields.extend(str(item.get("identity", {}).get("id") or "") for item in new_items)
    digest = hashlib.sha256("\x1f".join(fields).encode("utf-8")).hexdigest()[:24]
    return f"change_{digest}"


class GitHubChangeImpactService:
    """Map compare hunks to old/new symbols and bounded semantic impact."""

    def __init__(
        self,
        history_service: GitHubHistoryService,
        snapshot_service: Any,
        cache_repository: ProviderCacheRepository | None = None,
    ) -> None:
        self.history_service = history_service
        self.snapshot_service = snapshot_service
        self.cache_repository = cache_repository

    def _snapshot(
        self,
        repo_url: str,
        *,
        commit_sha: str,
        paths: list[str],
    ) -> dict[str, Any]:
        query = " ".join(paths)
        result = self.snapshot_service.snapshot(repo_url, query=query, ref=commit_sha)
        if result.get("ok") is True:
            result = {
                **result,
                "commit_sha": str(result.get("commit_sha") or commit_sha),
                "requested_ref": str(result.get("requested_ref") or commit_sha),
            }
        return result

    @staticmethod
    def _graph(snapshot: dict[str, Any]) -> RepositoryGraphIndex | None:
        if snapshot.get("ok") is not True:
            return None
        try:
            return RepositoryGraphIndex(snapshot)
        except Exception:
            return None

    @staticmethod
    def _semantic(graph: RepositoryGraphIndex | None) -> AdvancedModuleSemanticIndex | None:
        if graph is None:
            return None
        try:
            return AdvancedModuleSemanticIndex(graph)
        except Exception:
            return None

    @staticmethod
    def _impact(
        index: AdvancedModuleSemanticIndex | None,
        symbol: dict[str, Any],
        *,
        depth: int,
        max_files: int,
        max_edges: int,
    ) -> dict[str, Any]:
        if index is None:
            return {"ok": False, "status": "unavailable", "error": "semantic_index_unavailable"}
        query = str(symbol.get("qualified_name") or symbol.get("name") or "")
        if not query:
            return {"ok": False, "status": "unavailable", "error": "empty_symbol_query"}
        try:
            return index.impact(
                query,
                depth=depth,
                max_files=max_files,
                max_edges=max_edges,
            )
        except Exception as exc:
            return {
                "ok": False,
                "status": "unavailable",
                "error": f"{type(exc).__name__}: {exc}",
            }

    def analyze(
        self,
        repo_url: str,
        base: str,
        head: str,
        *,
        comparison: dict[str, Any] | None = None,
        base_repo_url: str = "",
        head_repo_url: str = "",
        max_files: int | None = None,
        max_symbols: int | None = None,
        depth: int = 2,
        max_impact_files: int = 40,
        max_edges: int = 160,
    ) -> dict[str, Any]:
        file_limit = max_files or _env_int(
            "GITHUB_CHANGE_IMPACT_MAX_FILES", 20, minimum=1, maximum=50
        )
        symbol_limit = max_symbols or _env_int(
            "GITHUB_CHANGE_IMPACT_MAX_SYMBOLS", 100, minimum=1, maximum=300
        )
        file_limit = max(1, min(int(file_limit), 50))
        symbol_limit = max(1, min(int(symbol_limit), 300))
        bounded_depth = max(1, min(int(depth), 4))
        bounded_impact_files = max(1, min(int(max_impact_files), 100))
        bounded_edges = max(1, min(int(max_edges), 500))
        patch_limit = _env_int(
            "GITHUB_CHANGE_IMPACT_MAX_PATCH_CHARS",
            160_000,
            minimum=1_000,
            maximum=1_000_000,
        )

        compared = comparison or self.history_service.compare(
            repo_url,
            base,
            head,
            max_files=file_limit,
            max_patch_chars=patch_limit,
        )
        if compared.get("ok") is not True:
            return compared
        base_ref = dict(compared.get("base") or {})
        head_ref = dict(compared.get("head") or {})
        base_sha = str(base_ref.get("commit_sha") or "")
        head_sha = str(head_ref.get("commit_sha") or "")
        repository = str(compared.get("repository") or "")
        base_repository = str(base_ref.get("repository") or repository)
        head_repository = str(head_ref.get("repository") or repository)
        base_snapshot_repo_url = str(
            base_repo_url or base_ref.get("repository_url") or repo_url
        )
        head_snapshot_repo_url = str(
            head_repo_url or head_ref.get("repository_url") or repo_url
        )
        cross_repository = bool(
            base_repository
            and head_repository
            and base_repository.casefold() != head_repository.casefold()
        )
        budget = {
            "max_files": file_limit,
            "max_symbols": symbol_limit,
            "depth": bounded_depth,
            "max_impact_files": bounded_impact_files,
            "max_edges": bounded_edges,
            "max_patch_chars": patch_limit,
        }
        cache_key = provider_cache_key(
            kind="change-impact",
            repository=repository,
            request=budget,
            immutable_refs={
                "base_repository": base_repository,
                "base_sha": base_sha,
                "head_repository": head_repository,
                "head_sha": head_sha,
            },
        )
        if self.cache_repository is not None and base_sha and head_sha:
            cached = self.cache_repository.get(cache_key)
            if cached is not None:
                return {
                    **cached.payload,
                    "cache_hit": True,
                    "cache_mode": "persistent",
                    "cache_schema_version": cached.schema_version,
                }
        files = [
            dict(item)
            for item in compared.get("files", [])
            if isinstance(item, dict) and _source_path(str(item.get("filename") or item.get("previous_filename") or ""))
        ][:file_limit]
        old_paths = sorted(
            {
                str(item.get("previous_filename") or item.get("filename") or "")
                for item in files
                if str(item.get("status") or "") != "added"
            }
        )
        new_paths = sorted(
            {
                str(item.get("filename") or "")
                for item in files
                if str(item.get("status") or "") != "removed"
            }
        )
        base_snapshot = self._snapshot(
            base_snapshot_repo_url, commit_sha=base_sha, paths=old_paths
        )
        head_snapshot = self._snapshot(
            head_snapshot_repo_url, commit_sha=head_sha, paths=new_paths
        )
        base_graph = self._graph(base_snapshot)
        head_graph = self._graph(head_snapshot)
        base_index = self._semantic(base_graph)
        head_index = self._semantic(head_graph)
        base_snapshot_paths = {
            str(item.get("path") or "")
            for item in base_snapshot.get("files", [])
            if isinstance(item, dict)
        }
        head_snapshot_paths = {
            str(item.get("path") or "")
            for item in head_snapshot.get("files", [])
            if isinstance(item, dict)
        }

        uncertainties: list[dict[str, Any]] = []
        for side, snapshot, snapshot_repository in (
            ("base", base_snapshot, base_repository),
            ("head", head_snapshot, head_repository),
        ):
            if snapshot.get("ok") is not True:
                uncertainties.append(
                    {
                        "kind": f"{side}_snapshot_unavailable",
                        "repository": snapshot_repository,
                        "commit_sha": base_sha if side == "base" else head_sha,
                        "error": str(snapshot.get("error") or "snapshot_unavailable"),
                    }
                )
        old_symbols: list[dict[str, Any]] = []
        new_symbols: list[dict[str, Any]] = []
        file_changes: list[dict[str, Any]] = []
        for item in files:
            status = str(item.get("status") or "")
            old_path = str(item.get("previous_filename") or item.get("filename") or "")
            new_path = str(item.get("filename") or "")
            old_ranges = _ranges(item, "old")
            new_ranges = _ranges(item, "new")
            all_symbols = bool(item.get("patch_truncated")) or not item.get("hunks")
            old_found = status == "added" or old_path in base_snapshot_paths
            new_found = status == "removed" or new_path in head_snapshot_paths
            if not old_found:
                uncertainties.append({"kind": "missing_base_file", "path": old_path})
            if not new_found:
                uncertainties.append({"kind": "missing_head_file", "path": new_path})
            if all_symbols:
                uncertainties.append(
                    {
                        "kind": "whole_file_symbol_fallback",
                        "path": new_path or old_path,
                        "reason": "patch_missing_or_truncated",
                    }
                )
            old_items = (
                _changed_symbols(
                    base_graph,
                    base_snapshot,
                    path=old_path,
                    ranges=old_ranges,
                    all_symbols=all_symbols or status == "removed",
                )
                if status != "added"
                else []
            )
            new_items = (
                _changed_symbols(
                    head_graph,
                    head_snapshot,
                    path=new_path,
                    ranges=new_ranges,
                    all_symbols=all_symbols or status == "added",
                )
                if status != "removed"
                else []
            )
            old_symbols.extend(old_items)
            new_symbols.extend(new_items)
            file_changes.append(
                {
                    "status": status,
                    "old_path": old_path if status != "added" else "",
                    "new_path": new_path if status != "removed" else "",
                    "hunks": list(item.get("hunks") or []),
                    "patch_truncated": bool(item.get("patch_truncated")),
                    "old_symbol_count": len(old_items),
                    "new_symbol_count": len(new_items),
                }
            )

        old_buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        new_buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for item in old_symbols:
            old_buckets[_symbol_key(item)].append(item)
        for item in new_symbols:
            new_buckets[_symbol_key(item)].append(item)

        changes: list[dict[str, Any]] = []
        for key in sorted(set(old_buckets) | set(new_buckets)):
            old_items = old_buckets.get(key, [])
            new_items = new_buckets.get(key, [])
            if len(old_items) > 1 or len(new_items) > 1:
                change_type = "ambiguous"
                uncertainties.append(
                    {
                        "kind": "ambiguous_symbol_pair",
                        "symbol_key": list(key),
                        "old_count": len(old_items),
                        "new_count": len(new_items),
                    }
                )
            elif not old_items:
                change_type = "added"
            elif not new_items:
                change_type = "removed"
            else:
                old_path = str(old_items[0].get("evidence", {}).get("path") or "")
                new_path = str(new_items[0].get("evidence", {}).get("path") or "")
                change_type = "moved" if old_path != new_path else "modified"
            changes.append(
                {
                    "id": _change_id(base_sha, head_sha, change_type, old_items, new_items),
                    "type": change_type,
                    "symbol_key": list(key),
                    "old": old_items,
                    "new": new_items,
                    "signature_changed": bool(
                        len(old_items) == 1
                        and len(new_items) == 1
                        and str(old_items[0].get("signature") or "")
                        != str(new_items[0].get("signature") or "")
                    ),
                }
            )

        if len(changes) > symbol_limit:
            uncertainties.append(
                {
                    "kind": "symbol_budget_exhausted",
                    "provider_symbol_count": len(changes),
                    "max_symbols": symbol_limit,
                }
            )
        changes = changes[:symbol_limit]
        affected_files: dict[str, set[str]] = defaultdict(set)
        tests: dict[str, dict[str, Any]] = {}
        missing_test_symbols: list[str] = []
        for change in changes:
            selected = (
                change.get("new", [])[0]
                if len(change.get("new", [])) == 1
                else (
                    change.get("old", [])[0]
                    if len(change.get("old", [])) == 1
                    else None
                )
            )
            if not isinstance(selected, dict):
                change["impact"] = {
                    "ok": False,
                    "status": "ambiguous",
                    "error": "change_has_no_unique_symbol",
                }
                continue
            index = base_index if change.get("type") == "removed" else head_index
            impact = self._impact(
                index,
                selected,
                depth=bounded_depth,
                max_files=bounded_impact_files,
                max_edges=bounded_edges,
            )
            change["impact"] = impact
            for raw in impact.get("files", []):
                if not isinstance(raw, dict):
                    continue
                path = str(raw.get("path") or "")
                if path:
                    affected_files[path].update(str(reason) for reason in raw.get("reasons", []))
            symbol_tests = []
            for raw in impact.get("tests", []):
                if not isinstance(raw, dict):
                    continue
                path = str(raw.get("path") or "")
                if path:
                    tests[path] = dict(raw)
                    symbol_tests.append(path)
            selected_path = str(selected.get("evidence", {}).get("path") or "")
            if not symbol_tests and not _test_path(selected_path):
                missing_test_symbols.append(
                    str(selected.get("qualified_name") or selected.get("name") or "")
                )

        counts = Counter(str(item.get("type") or "") for item in changes)
        provider_status = "complete"
        if base_snapshot.get("ok") is not True or head_snapshot.get("ok") is not True or uncertainties:
            provider_status = "partial"
        result = {
            "ok": True,
            "status": "resolved",
            "provider_status": provider_status,
            "repository": repository,
            "base_repository": base_repository,
            "head_repository": head_repository,
            "cross_repository": cross_repository,
            "base": base_ref,
            "head": head_ref,
            "compare": {
                "status": str(compared.get("status") or ""),
                "ahead_by": int(compared.get("ahead_by") or 0),
                "behind_by": int(compared.get("behind_by") or 0),
                "total_commits": int(compared.get("total_commits") or 0),
                "truncated": bool(compared.get("truncated")),
            },
            "snapshots": {
                "base": {
                    "ok": bool(base_snapshot.get("ok")),
                    "repository": base_repository,
                    "commit_sha": base_sha,
                    "tree_sha": str(base_snapshot.get("tree_sha") or ""),
                    "file_count": int(base_snapshot.get("file_count") or 0),
                    "missing_changed_paths": sorted(set(old_paths) - base_snapshot_paths),
                },
                "head": {
                    "ok": bool(head_snapshot.get("ok")),
                    "repository": head_repository,
                    "commit_sha": head_sha,
                    "tree_sha": str(head_snapshot.get("tree_sha") or ""),
                    "file_count": int(head_snapshot.get("file_count") or 0),
                    "missing_changed_paths": sorted(set(new_paths) - head_snapshot_paths),
                },
            },
            "file_changes": file_changes,
            "changes": changes,
            "summary": {
                "source_file_count": len(files),
                "symbol_change_count": len(changes),
                "added": counts["added"],
                "removed": counts["removed"],
                "modified": counts["modified"],
                "moved": counts["moved"],
                "ambiguous": counts["ambiguous"],
                "affected_file_count": len(affected_files),
                "test_count": len(tests),
                "missing_test_symbol_count": len(set(missing_test_symbols)),
            },
            "affected_files": [
                {"path": path, "reasons": sorted(reasons)}
                for path, reasons in sorted(affected_files.items())
            ],
            "tests": [tests[path] for path in sorted(tests)],
            "missing_test_symbols": sorted(set(missing_test_symbols)),
            "uncertainties": uncertainties,
            "truncated": bool(compared.get("truncated")) or len(changes) >= symbol_limit,
            "budget": budget,
        }
        if self.cache_repository is not None and base_sha and head_sha:
            self.cache_repository.put(
                cache_key=cache_key,
                kind="change-impact",
                repository=repository,
                payload=result,
                immutable_refs={
                    "base_repository": base_repository,
                    "base_sha": base_sha,
                    "head_repository": head_repository,
                    "head_sha": head_sha,
                },
                provider_status=provider_status,
                budget=budget,
                reuse_class="partial" if provider_status == "partial" else "complete",
                ttl_seconds=_env_int(
                    "GITHUB_PROVIDER_CACHE_TTL_SECONDS",
                    300,
                    minimum=0,
                    maximum=86_400,
                ),
            )
        return {
            **result,
            "cache_hit": False,
            "cache_schema_version": PROVIDER_CACHE_SCHEMA_VERSION,
        }
