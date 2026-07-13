from __future__ import annotations

from src.web.github_structure import RepositoryStructureIndex


SNAPSHOT = {
    "repository": "openai/example",
    "ref": "main",
    "tree_sha": "tree-123",
    "files": [
        {
            "path": "src/repository.py",
            "sha": "sha-repository",
            "content": """class UserRepository:\n    def load_user(self, user_id: str):\n        return user_id\n""",
        },
        {
            "path": "src/service.py",
            "sha": "sha-service",
            "content": """from .repository import UserRepository\n\nclass UserService:\n    def __init__(self, repository: UserRepository):\n        self.repository = repository\n\n    def get_user(self, user_id: str):\n        return self.repository.load_user(user_id)\n""",
        },
        {
            "path": "frontend/src/client.ts",
            "sha": "sha-client",
            "content": """export async function loadUser(id: string) {\n  return id;\n}\n""",
        },
        {
            "path": "frontend/src/api.ts",
            "sha": "sha-api",
            "content": """import { loadUser } from './client';\n\nexport const fetchUser = (id: string) => loadUser(id);\n""",
        },
    ],
}


def test_python_ast_extracts_qualified_definitions_and_stable_evidence():
    index = RepositoryStructureIndex(SNAPSHOT)

    definitions = index.definitions("load_user")

    assert definitions[0]["qualified_name"] == "UserRepository.load_user"
    assert definitions[0]["kind"] == "method"
    evidence = definitions[0]["evidence"]
    assert evidence == {
        "repository": "openai/example",
        "ref": "main",
        "tree_sha": "tree-123",
        "path": "src/repository.py",
        "file_sha": "sha-repository",
        "start_line": 2,
        "end_line": 3,
        "symbol": "UserRepository.load_user",
        "kind": "definition",
    }


def test_python_relative_import_is_resolved_to_snapshot_path():
    index = RepositoryStructureIndex(SNAPSHOT)

    edge = index.files["src/service.py"].imports[0]

    assert edge.module == ".repository"
    assert edge.names == ("UserRepository",)
    assert edge.resolved_path == "src/repository.py"
    assert edge.evidence.kind == "import"


def test_references_exclude_definition_line_and_keep_call_site():
    index = RepositoryStructureIndex(SNAPSHOT)

    references = index.references("load_user")

    assert references
    assert references[0]["evidence"]["path"] == "src/service.py"
    assert references[0]["evidence"]["start_line"] == 8
    assert "repository.load_user" in references[0]["context"]


def test_typescript_declarations_and_relative_imports_are_structured():
    index = RepositoryStructureIndex(SNAPSHOT)

    definitions = index.definitions("loadUser")
    api_import = index.files["frontend/src/api.ts"].imports[0]

    assert definitions[0]["language"] == "typescript"
    assert definitions[0]["kind"] == "function"
    assert api_import.module == "./client"
    assert api_import.resolved_path == "frontend/src/client.ts"


def test_inspect_returns_definitions_references_related_files_and_stats():
    index = RepositoryStructureIndex(SNAPSHOT)

    result = index.inspect("UserRepository")

    assert result["ok"] is True
    assert result["definitions"]
    assert {item["path"] for item in result["related_files"]} >= {
        "src/repository.py",
        "src/service.py",
    }
    assert result["stats"]["parser"] == "python_ast+js_ts_fallback"
    assert result["stats"]["resolved_import_count"] >= 2
