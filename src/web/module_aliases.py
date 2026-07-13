"""Snapshot-local module alias and import resolution."""

from __future__ import annotations

from dataclasses import dataclass
import json
import posixpath
from pathlib import PurePosixPath
import re
from typing import Any

from src.web.github_structure import _resolve_relative_import


@dataclass(frozen=True)
class ModuleAlias:
    pattern: str
    targets: tuple[str, ...]
    base_path: str
    config_path: str


def _normalized(value: str | PurePosixPath) -> str:
    return posixpath.normpath(str(value)).lstrip("./")


def _json_with_comments(text: str) -> dict[str, Any]:
    stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    stripped = re.sub(r"(^|\s)//.*$", r"\1", stripped, flags=re.MULTILINE)
    stripped = re.sub(r",\s*([}\]])", r"\1", stripped)
    value = json.loads(stripped)
    return dict(value) if isinstance(value, dict) else {}


def load_module_aliases(snapshot: dict[str, Any]) -> tuple[ModuleAlias, ...]:
    aliases: list[ModuleAlias] = []
    for raw in snapshot.get("files", []):
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("path") or "")
        if PurePosixPath(path).name not in {"tsconfig.json", "jsconfig.json"}:
            continue
        try:
            payload = _json_with_comments(str(raw.get("content") or ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        compiler = payload.get("compilerOptions")
        if not isinstance(compiler, dict):
            continue
        config_dir = PurePosixPath(path).parent
        base_url = str(compiler.get("baseUrl") or ".")
        base_path = _normalized(config_dir / base_url)
        paths = compiler.get("paths")
        if not isinstance(paths, dict):
            continue
        for pattern, raw_targets in paths.items():
            if isinstance(raw_targets, str):
                targets = (raw_targets,)
            elif isinstance(raw_targets, list):
                targets = tuple(str(item) for item in raw_targets if str(item).strip())
            else:
                targets = ()
            if str(pattern).strip() and targets:
                aliases.append(
                    ModuleAlias(
                        pattern=str(pattern),
                        targets=targets,
                        base_path=base_path,
                        config_path=path,
                    )
                )
    return tuple(sorted(aliases, key=lambda item: (item.config_path, item.pattern)))


def _match_alias(pattern: str, module: str) -> str | None:
    if "*" not in pattern:
        return "" if pattern == module else None
    prefix, suffix = pattern.split("*", 1)
    if not module.startswith(prefix) or not module.endswith(suffix):
        return None
    end = len(module) - len(suffix) if suffix else len(module)
    return module[len(prefix) : end]


def _candidate_paths(base: str) -> tuple[str, ...]:
    return (
        base,
        f"{base}.py",
        f"{base}/__init__.py",
        f"{base}.ts",
        f"{base}.tsx",
        f"{base}.js",
        f"{base}.jsx",
        f"{base}.mjs",
        f"{base}.cjs",
        f"{base}.java",
        f"{base}/index.ts",
        f"{base}/index.tsx",
        f"{base}/index.js",
        f"{base}/index.jsx",
    )


def _unique_match(candidate: str, paths: set[str]) -> str:
    normalized = _normalized(candidate)
    if normalized in paths:
        return normalized
    suffix = f"/{normalized}"
    matches = sorted(path for path in paths if path.endswith(suffix))
    return matches[0] if len(matches) == 1 else ""


def resolve_snapshot_import(
    source_path: str,
    module: str,
    paths: set[str],
    aliases: tuple[ModuleAlias, ...],
) -> str:
    resolved = _resolve_relative_import(source_path, module, paths)
    if resolved:
        return resolved
    for alias in aliases:
        wildcard = _match_alias(alias.pattern, module)
        if wildcard is None:
            continue
        for target in alias.targets:
            replaced = target.replace("*", wildcard)
            base = _normalized(PurePosixPath(alias.base_path) / replaced)
            for candidate in _candidate_paths(base):
                matched = _unique_match(candidate, paths)
                if matched:
                    return matched
    if not module.startswith((".", "/")):
        dotted = module.replace(".", "/")
        for candidate in (f"{dotted}.java", f"src/main/java/{dotted}.java"):
            matched = _unique_match(candidate, paths)
            if matched:
                return matched
    return ""
