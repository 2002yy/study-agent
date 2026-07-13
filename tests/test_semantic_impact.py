from __future__ import annotations

from copy import deepcopy

from src.web.repository_graph import RepositoryGraphIndex
from src.web.semantic_impact import SemanticImpactIndex


SNAPSHOT = {
    "repository": "openai/example",
    "ref": "main",
    "tree_sha": "tree-semantic-1",
    "snapshot_run_id": "rag_semantic_1",
    "files": [
        {
            "path": "src/base.py",
            "sha": "sha-base",
            "content": """class Repository:\n    def save(self, value: str):\n        return value\n""",
        },
        {
            "path": "src/user_repo.py",
            "sha": "sha-user-repo",
            "content": """from .base import Repository\n\nclass UserRepository(Repository):\n    def save(self, value: str):\n        return value\n""",
        },
        {
            "path": "src/audit_repo.py",
            "sha": "sha-audit-repo",
            "content": """class AuditRepository:\n    def save(self, value: str):\n        return value\n""",
        },
        {
            "path": "src/service.py",
            "sha": "sha-service",
            "content": """from .user_repo import UserRepository\n\nclass UserService:\n    def __init__(self, repo: UserRepository):\n        self.repo = repo\n\n    def execute(self, value: str):\n        return self.repo.save(value)\n""",
        },
        {
            "path": "tests/test_service.py",
            "sha": "sha-test-service",
            "content": """from src.service import UserService\n\ndef test_execute():\n    service = UserService(None)\n    assert service.execute('x') == 'x'\n""",
        },
    ],
}


def _index(snapshot: dict = SNAPSHOT) -> SemanticImpactIndex:
    return SemanticImpactIndex(RepositoryGraphIndex(snapshot))


def test_simple_name_remains_ambiguous_when_multiple_methods_share_it():
    result = _index().resolve("save")

    assert result["status"] == "ambiguous"
    assert result["selected"] is None
    assert {item["qualified_name"] for item in result["candidates"]} >= {
        "Repository.save",
        "UserRepository.save",
        "AuditRepository.save",
    }


def test_receiver_type_disambiguates_same_name_method_call():
    index = _index()
    call = next(
        edge
        for edge in index.calls
        if edge["caller"] == "UserService.execute"
        and edge["callee"].endswith(".save")
    )

    assert call["resolution_status"] == "resolved"
    assert call["resolved_symbol"] == "UserRepository.save"
    assert call["resolved_path"] == "src/user_repo.py"
    assert "receiver_type" in call["semantic_resolution"]["selected"]["semantic_reasons"]
    assert call["target_symbol_id"].startswith("symbol_")


def test_class_and_method_implementations_are_reported():
    index = _index()

    class_implementations = index.implementations("Repository")
    method_implementations = index.implementations("Repository.save")

    assert any(item.get("child") == "UserRepository" for item in class_implementations)
    assert any(
        item.get("implementation_kind") == "method_override"
        and item.get("symbol", {}).get("qualified_name") == "UserRepository.save"
        for item in method_implementations
    )


def test_bounded_impact_includes_upstream_service_and_test_file():
    result = _index().impact("UserRepository.save", depth=3)

    assert result["resolution"]["status"] == "resolved"
    assert any(
        edge.get("caller") == "UserService.execute"
        and edge.get("impact_direction") == "upstream"
        for edge in result["edges"]
    )
    assert {item["path"] for item in result["files"]} >= {
        "src/user_repo.py",
        "src/service.py",
    }
    assert {item["path"] for item in result["tests"]} == {
        "tests/test_service.py"
    }
    assert result["truncated"] is False


def test_symbol_identity_is_stable_for_same_snapshot_and_changes_with_tree():
    first = _index().resolve("UserRepository.save")["selected"]["symbol_identity"]
    second = _index().resolve("UserRepository.save")["selected"]["symbol_identity"]
    changed_snapshot = deepcopy(SNAPSHOT)
    changed_snapshot["tree_sha"] = "tree-semantic-2"
    changed = _index(changed_snapshot).resolve("UserRepository.save")["selected"][
        "symbol_identity"
    ]

    assert first == second
    assert first["id"] != changed["id"]
