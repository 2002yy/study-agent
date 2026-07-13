"""Optional LSP enrichment contract with a safe no-server default.

The repository graph must remain usable without a language server. Adapters are
therefore injected and return structured availability/error states rather than
starting subprocesses from request handlers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class LspLocation:
    path: str
    start_line: int
    start_character: int = 0
    end_line: int = 0
    end_character: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LspQueryResult:
    status: str
    provider: str
    operation: str
    locations: tuple[LspLocation, ...] = ()
    type_text: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "locations": [location.to_dict() for location in self.locations],
        }


class LspAdapter(Protocol):
    @property
    def provider(self) -> str: ...

    def definition(self, path: str, line: int, character: int) -> LspQueryResult: ...

    def references(self, path: str, line: int, character: int) -> LspQueryResult: ...

    def type_info(self, path: str, line: int, character: int) -> LspQueryResult: ...


class NullLspAdapter:
    provider = "none"

    def _unavailable(self, operation: str) -> LspQueryResult:
        return LspQueryResult(
            status="unavailable",
            provider=self.provider,
            operation=operation,
            error="lsp_adapter_not_configured",
        )

    def definition(self, path: str, line: int, character: int) -> LspQueryResult:
        del path, line, character
        return self._unavailable("definition")

    def references(self, path: str, line: int, character: int) -> LspQueryResult:
        del path, line, character
        return self._unavailable("references")

    def type_info(self, path: str, line: int, character: int) -> LspQueryResult:
        del path, line, character
        return self._unavailable("type_info")


class CallbackLspAdapter:
    """Adapter for an externally managed LSP client.

    The callback receives an operation and JSON-safe arguments. It must not be a
    raw shell-command executor; process lifecycle, workspace trust, and timeouts
    belong to the future RepositoryRun/SandboxRun boundary.
    """

    def __init__(
        self,
        provider: str,
        callback: Callable[[str, dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._provider = provider.strip() or "callback"
        self.callback = callback

    @property
    def provider(self) -> str:
        return self._provider

    def _query(self, operation: str, path: str, line: int, character: int) -> LspQueryResult:
        try:
            payload = self.callback(
                operation,
                {
                    "path": path,
                    "line": max(0, int(line)),
                    "character": max(0, int(character)),
                },
            )
        except Exception as exc:
            return LspQueryResult(
                status="failed",
                provider=self.provider,
                operation=operation,
                error=f"{type(exc).__name__}: {exc}",
            )
        locations = tuple(
            LspLocation(
                path=str(item.get("path") or ""),
                start_line=max(0, int(item.get("start_line") or 0)),
                start_character=max(0, int(item.get("start_character") or 0)),
                end_line=max(0, int(item.get("end_line") or 0)),
                end_character=max(0, int(item.get("end_character") or 0)),
            )
            for item in payload.get("locations", [])
            if isinstance(item, dict) and str(item.get("path") or "")
        )
        status = str(payload.get("status") or ("ok" if locations else "empty"))
        return LspQueryResult(
            status=status,
            provider=self.provider,
            operation=operation,
            locations=locations,
            type_text=str(payload.get("type_text") or ""),
            error=str(payload.get("error") or ""),
        )

    def definition(self, path: str, line: int, character: int) -> LspQueryResult:
        return self._query("definition", path, line, character)

    def references(self, path: str, line: int, character: int) -> LspQueryResult:
        return self._query("references", path, line, character)

    def type_info(self, path: str, line: int, character: int) -> LspQueryResult:
        return self._query("type_info", path, line, character)
