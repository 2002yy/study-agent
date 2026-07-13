from __future__ import annotations

from src.web.repository_graph import RepositoryGraphIndex


SNAPSHOT = {
    "repository": "openai/example",
    "ref": "main",
    "tree_sha": "tree-graph",
    "snapshot_run_id": "rag_graph_1",
    "files": [
        {
            "path": "src/repository.py",
            "sha": "sha-py-repository",
            "content": """class BaseRepository:\n    pass\n\nclass UserRepository(BaseRepository):\n    def load_user(self, user_id: str):\n        return user_id\n""",
        },
        {
            "path": "src/service.py",
            "sha": "sha-py-service",
            "content": """from .repository import UserRepository\n\nclass UserService:\n    def __init__(self, repository: UserRepository):\n        self.repository = repository\n\n    def get_user(self, user_id: str):\n        return self.repository.load_user(user_id)\n""",
        },
        {
            "path": "frontend/tsconfig.json",
            "sha": "sha-tsconfig",
            "content": """{\n  // aliases are resolved inside the snapshot\n  \"compilerOptions\": {\n    \"baseUrl\": \".\",\n    \"paths\": {\"@/*\": [\"src/*\",],},\n  },\n}\n""",
        },
        {
            "path": "frontend/src/client.ts",
            "sha": "sha-ts-client",
            "content": """export function loadUser(id: string) {\n  return id;\n}\n""",
        },
        {
            "path": "frontend/src/api.ts",
            "sha": "sha-ts-api",
            "content": """import { loadUser } from '@/client';\n\nexport const fetchUser = (id: string) => loadUser(id);\n""",
        },
        {
            "path": "src/main/java/example/BaseService.java",
            "sha": "sha-java-base",
            "content": """package example;\npublic class BaseService {}\n""",
        },
        {
            "path": "src/main/java/example/UserRepository.java",
            "sha": "sha-java-repository",
            "content": """package example;\npublic class UserRepository {\n  public String load(String id) { return id; }\n}\n""",
        },
        {
            "path": "src/main/java/example/UserService.java",
            "sha": "sha-java-service",
            "content": """package example;\nimport example.UserRepository;\npublic class UserService extends BaseService {\n  private final UserRepository repository = new UserRepository();\n  public String getUser(String id) { return repository.load(id); }\n}\n""",
        },
    ],
}


def test_python_callers_and_inheritance_are_resolved_to_evidence():
    index = RepositoryGraphIndex(SNAPSHOT)

    callers = index.callers("load_user")
    hierarchy = index.hierarchy("UserRepository")

    assert callers[0]["caller"] == "UserService.get_user"
    assert callers[0]["resolved_symbol"] == "UserRepository.load_user"
    assert callers[0]["resolved_path"] == "src/repository.py"
    assert callers[0]["target_evidence"]["file_sha"] == "sha-py-repository"
    assert hierarchy[0]["parent"] == "BaseRepository"
    assert hierarchy[0]["resolved_path"] == "src/repository.py"


def test_typescript_paths_alias_resolves_import_and_call_target():
    index = RepositoryGraphIndex(SNAPSHOT)

    alias_edge = next(
        edge for edge in index.imports if edge["module"] == "@/client"
    )
    callees = index.callees("fetchUser")

    assert alias_edge["resolved_path"] == "frontend/src/client.ts"
    assert callees[0]["callee"] == "loadUser"
    assert callees[0]["resolved_symbol"] == "loadUser"
    assert callees[0]["resolved_path"] == "frontend/src/client.ts"


def test_java_hierarchy_constructor_and_method_calls_are_structured():
    index = RepositoryGraphIndex(SNAPSHOT)

    hierarchy = index.hierarchy("UserService")
    constructors = [
        edge
        for edge in index.callees("UserService")
        if edge["kind"] == "constructor"
    ]
    callers = index.callers("load")

    assert hierarchy[0]["parent"] == "BaseService"
    assert hierarchy[0]["resolved_path"].endswith("BaseService.java")
    assert constructors[0]["resolved_path"].endswith("UserRepository.java")
    assert callers[0]["caller"] == "UserService.getUser"
    assert callers[0]["resolved_path"].endswith("UserRepository.java")


def test_inspect_reports_graph_sections_and_parser_stats():
    result = RepositoryGraphIndex(SNAPSHOT).inspect("loadUser")

    assert result["ok"] is True
    assert result["definitions"]
    assert result["callers"]
    assert result["callees"] == []
    assert result["hierarchy"] == []
    assert {item["path"] for item in result["related_files"]} >= {
        "frontend/src/client.ts",
        "frontend/src/api.ts",
    }
    stats = result["stats"]
    assert stats["parser"] == "tree_sitter+legacy_fallback"
    assert stats["tree_sitter_file_count"] == 7
    assert stats["module_alias_count"] == 1
    assert stats["call_count"] >= 4
    assert stats["resolved_call_count"] >= 3
    assert stats["inheritance_count"] >= 2
