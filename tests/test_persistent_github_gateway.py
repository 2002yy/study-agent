from __future__ import annotations

from src.web.persistent_tool_gateway import PersistentGeneralWebGateway


class FakeSnapshotService:
    def __init__(self, *, result_count: int = 1) -> None:
        self.result_count = result_count
        self.search_calls: list[tuple[str, str, int]] = []
        self.snapshot_calls: list[tuple[str, str, str]] = []
        self.structure_calls: list[tuple[str, str, str, int]] = []

    def search_repository(
        self,
        repo_url: str,
        query: str,
        *,
        ref: str = "",
        top_k: int = 12,
    ) -> dict:
        self.search_calls.append((repo_url, query, top_k))
        results = (
            [
                {
                    "path": "src/app.py",
                    "line_range": "L10-L20",
                    "sha": "sha-app",
                    "score": 12.0,
                }
            ]
            if self.result_count
            else []
        )
        return {
            "ok": True,
            "mode": "local_snapshot_hybrid",
            "repository": "openai/example",
            "query": query,
            "result_count": len(results),
            "results": results,
        }

    def snapshot(self, repo_url: str, *, query: str = "", ref: str = "") -> dict:
        self.snapshot_calls.append((repo_url, query, ref))
        return {
            "ok": True,
            "repository": "openai/example",
            "ref": ref or "main",
            "files": [],
        }

    def inspect_structure(
        self,
        repo_url: str,
        symbol: str,
        *,
        ref: str = "",
        top_k: int = 20,
    ) -> dict:
        self.structure_calls.append((repo_url, symbol, ref, top_k))
        return {
            "ok": True,
            "repository": "openai/example",
            "symbol": symbol,
            "definitions": [{"name": symbol}],
        }


def test_gateway_returns_local_hybrid_results_without_remote_search():
    service = FakeSnapshotService()
    gateway = PersistentGeneralWebGateway(service)  # type: ignore[arg-type]

    result = gateway.github_search(
        "https://github.com/openai/example",
        "prepare_chat_turn",
        max_results=6,
    )

    assert result["mode"] == "local_snapshot_hybrid"
    assert result["results"][0]["line_range"] == "L10-L20"
    assert service.search_calls == [
        ("https://github.com/openai/example", "prepare_chat_turn", 6)
    ]


def test_gateway_snapshot_uses_persistent_service():
    service = FakeSnapshotService()
    gateway = PersistentGeneralWebGateway(service)  # type: ignore[arg-type]

    result = gateway.github_snapshot(
        "https://github.com/openai/example",
        query="architecture",
        ref="main",
    )

    assert result["ok"] is True
    assert service.snapshot_calls == [
        ("https://github.com/openai/example", "architecture", "main")
    ]


def test_gateway_structure_uses_persistent_service():
    service = FakeSnapshotService()
    gateway = PersistentGeneralWebGateway(service)  # type: ignore[arg-type]

    result = gateway.github_structure(
        "https://github.com/openai/example",
        "prepare_chat_turn",
        ref="main",
        max_results=9,
    )

    assert result["definitions"][0]["name"] == "prepare_chat_turn"
    assert service.structure_calls == [
        (
            "https://github.com/openai/example",
            "prepare_chat_turn",
            "main",
            9,
        )
    ]
