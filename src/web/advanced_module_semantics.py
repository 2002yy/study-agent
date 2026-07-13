"""Module-qualified and overload-aware wrapper for repository semantics."""

from __future__ import annotations

import re
from typing import Any

from src.web.module_identity import ModuleSemanticIndex
from src.web.repository_graph import RepositoryGraphIndex


def _signature_query(value: str) -> tuple[str, str]:
    focused = str(value or "").strip()
    if "(" not in focused or not focused.endswith(")"):
        return focused, ""
    name, payload = focused.split("(", 1)
    return name.strip(), f"({payload}"


def _arity(signature: str) -> int | None:
    text = str(signature or "").strip()
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
        elif character in "])}>":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            count += 1
    return count


def _normalized_signature(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _correct_module_qualified(item: dict[str, Any]) -> dict[str, Any]:
    module = item.get("module_identity")
    if not isinstance(module, dict):
        return item
    module_name = str(module.get("module_name") or "")
    language = str(module.get("language") or "")
    qualified = str(item.get("qualified_name") or item.get("name") or "")
    if not module_name or not qualified:
        return item
    if language == "java":
        class_name = module_name.rsplit(".", 1)[-1]
        package = module_name.rsplit(".", 1)[0] if "." in module_name else ""
        if qualified == class_name or qualified.startswith(f"{class_name}."):
            value = f"{package}.{qualified}" if package else qualified
        else:
            value = f"{module_name}.{qualified}"
    else:
        value = f"{module_name}.{qualified}"
    return {**item, "module_qualified_name": value}


class AdvancedModuleSemanticIndex:
    """Adds module-qualified lookup and explicit overload candidate handling."""

    def __init__(self, graph: RepositoryGraphIndex) -> None:
        self.graph = graph
        self.base = ModuleSemanticIndex(graph)

    def _overload_candidates(
        self,
        definitions: list[dict[str, Any]],
        overload_group_id: str,
    ) -> list[dict[str, Any]]:
        return [
            item
            for item in definitions
            if str(item.get("overload_group_id") or "") == overload_group_id
        ]

    def inspect(self, symbol: str, *, top_k: int = 20) -> dict[str, Any]:
        query_name, requested_signature = _signature_query(symbol)
        result = self.base.inspect(query_name, top_k=max(top_k, 50))
        definitions = [
            _correct_module_qualified(dict(item))
            for item in result.get("definitions", [])
            if isinstance(item, dict)
        ]
        resolution = dict(result.get("resolution") or {})
        if isinstance(resolution.get("selected"), dict):
            resolution["selected"] = _correct_module_qualified(
                dict(resolution["selected"])
            )
        resolution["candidates"] = [
            _correct_module_qualified(dict(item))
            for item in resolution.get("candidates", [])
            if isinstance(item, dict)
        ]

        module_exact = [
            item
            for item in definitions
            if str(item.get("module_qualified_name") or "").casefold()
            == query_name.casefold()
        ]
        if len(module_exact) == 1:
            resolution = {
                **resolution,
                "status": "resolved",
                "selected": module_exact[0],
                "candidates": module_exact,
                "module_qualified_match": True,
            }
        elif len(module_exact) > 1:
            resolution = {
                **resolution,
                "status": "ambiguous",
                "selected": None,
                "candidates": module_exact,
                "module_qualified_match": True,
            }

        selected = resolution.get("selected")
        selected = selected if isinstance(selected, dict) else None
        group_id = str(selected.get("overload_group_id") or "") if selected else ""
        if not group_id:
            candidate_groups = {
                str(item.get("overload_group_id") or "")
                for item in resolution.get("candidates", [])
                if isinstance(item, dict) and str(item.get("overload_group_id") or "")
            }
            if len(candidate_groups) == 1:
                group_id = next(iter(candidate_groups))

        overload_candidates = self._overload_candidates(definitions, group_id) if group_id else []
        if overload_candidates:
            if requested_signature:
                requested_arity = _arity(requested_signature)
                exact = [
                    item
                    for item in overload_candidates
                    if _normalized_signature(str(item.get("signature") or ""))
                    == _normalized_signature(requested_signature)
                ]
                arity_matches = [
                    item
                    for item in overload_candidates
                    if requested_arity is not None
                    and _arity(str(item.get("signature") or "")) == requested_arity
                ]
                matches = exact or arity_matches
                resolution = {
                    **resolution,
                    "status": "resolved" if len(matches) == 1 else "ambiguous",
                    "selected": matches[0] if len(matches) == 1 else None,
                    "candidates": matches or overload_candidates,
                    "overload_group_id": group_id,
                    "requested_signature": requested_signature,
                }
            elif len(overload_candidates) > 1:
                resolution = {
                    **resolution,
                    "status": "ambiguous",
                    "selected": None,
                    "candidates": overload_candidates,
                    "overload_group_id": group_id,
                    "requested_signature": "",
                }

        return {
            **result,
            "symbol": symbol,
            "query_name": query_name,
            "query_signature": requested_signature,
            "definitions": definitions[: max(1, min(top_k, 100))],
            "resolution": resolution,
        }

    def impact(self, symbol: str, **kwargs: Any) -> dict[str, Any]:
        inspected = self.inspect(symbol, top_k=50)
        resolution = dict(inspected.get("resolution") or {})
        selected = resolution.get("selected")
        query_name, requested_signature = _signature_query(symbol)
        target = (
            str(selected.get("qualified_name") or selected.get("name") or "")
            if isinstance(selected, dict)
            else query_name
        )
        result = self.base.impact(target, **kwargs)
        return {
            **result,
            "symbol": symbol,
            "query_name": query_name,
            "query_signature": requested_signature,
            "resolution": resolution,
        }
