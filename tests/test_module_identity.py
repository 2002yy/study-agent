from __future__ import annotations

from src.application.github_graph_service import GitHubGraphService
from src.web.advanced_module_semantics import AdvancedModuleSemanticIndex
from src.web.lsp_adapter import CallbackLspAdapter, NullLspAdapter
from src.web.module_identity import ModuleGraph
from src.web.repository_graph import RepositoryGraphIndex
from src.web.structure_quality import (
    ImpactGoldenCase,
    ResolutionGoldenCase,
    evaluate_structure_quality,
)


SNAPSHOT = {
    "ok": True,
    "repository": "openai/example",
    "ref": "main",
    "tree_sha": "tree-module-1",
    "snapshot_run_id": "rag_module_1",
    "cache_hit": True,
    "cache_mode": "exact",
    "files": [
        {
            "path": "src/core.ts",
            "sha": "sha-ts-core",
            "content": "export function loadUser(id: string) { return id; }\n",
        },
        {
            "path": "src/legacy.ts",
            "sha": "sha-ts-legacy",
            "content": "export function loadUser(id: string) { return `legacy:${id}`; }\n",
        },
        {
            "path": "src/index.ts",
            "sha": "sha-ts-index",
            "content": "export { loadUser } from './core';\n",
        },
        {
            "path": "src/app.ts",
            "sha": "sha-ts-app",
            "content": "import { loadUser } from './index';\nexport function run() { return loadUser('1'); }\n",
        },
        {
            "path": "src/app.test.ts",
            "sha": "sha-ts-test",
            "content": "import { run } from './app';\ntest('run', () => expect(run()).toBe('1'));\n",
        },
        {
            "path": "pkg/core.py",
            "sha": "sha-py-core",
            "content": "class Service:\n    pass\n",
        },
        {
            "path": "pkg/legacy.py",
            "sha": "sha-py-legacy",
            "content": "class Service:\n    pass\n",
        },
        {
            "path": "pkg/__init__.py",
            "sha": "sha-py-init",
            "content": "from .core import Service\n",
        },
        {
            "path": "app.py",
            "sha": "sha-py-app",
            "content": "from pkg import Service\n\ndef make():\n    return Service()\n",
        },
        {
            "path": "src/main/java/com/alpha/UserService.java",
            "sha": "sha-java-alpha",
            "content": """package com.alpha;
public class UserService {
    public String load(String id) { return id; }
    public String load(String id, int retry) { return id; }
}
""",
        },
        {
            "path": "src/main/java/com/beta/UserService.java",
            "sha": "sha-java-beta",
            "content": """package com.beta;
public class UserService {
    public String load(String id) { return id; }
}
""",
        },
    ],
}


class FakeSnapshotService:
    def snapshot(
        self,
        repo_url: str,
        *,
        query: str = "",
        ref: str = "",
        force_refresh: bool = False,
    ) -> dict:
        del repo_url, query, force_refresh
        return {**SNAPSHOT, "ref": ref or "main"}


def _index() -> AdvancedModuleSemanticIndex:
    return AdvancedModuleSemanticIndex(RepositoryGraphIndex(SNAPSHOT))


def test_typescript_barrel_reexport_repairs_ambiguous_call_target():
    index = _index()
    call = next(
        edge
        for edge in index.base.base.calls
        if edge.get("caller") == "run" and edge.get("callee") == "loadUser"
    )

    assert call["resolution_status"] == "resolved"
    assert call["resolved_path"] == "src/core.ts"
    assert call["module_resolution"]["status"] == "resolved"
    assert call["module_resolution"]["export_chain"] == ["src/index.ts"]


def test_python_package_root_reexport_repairs_constructor_target():
    index = _index()
    call = next(
        edge
        for edge in index.base.base.calls
        if edge.get("caller") == "make" and edge.get("callee") == "Service"
    )

    assert call["resolution_status"] == "resolved"
    assert call["resolved_path"] == "pkg/core.py"
    assert call["module_resolution"]["export_chain"] == ["pkg/__init__.py"]


def test_module_identities_and_export_edges_are_versioned():
    modules = ModuleGraph(RepositoryGraphIndex(SNAPSHOT))

    assert modules.modules_by_path["pkg/__init__.py"].module_name == "pkg"
    assert modules.modules_by_path["src/index.ts"].module_name == "src"
    assert modules.modules_by_path[
        "src/main/java/com/alpha/UserService.java"
    ].module_name == "com.alpha.UserService"
    assert {edge.kind for edge in modules.exports} >= {
        "re_export",
        "python_re_export",
    }
    assert all(edge.source_module_id.startswith("module_") for edge in modules.exports)


def test_java_package_identity_disambiguates_same_class_name():
    result = _index().inspect("com.beta.UserService.load")

    assert result["resolution"]["status"] == "resolved"
    selected = result["resolution"]["selected"]
    assert selected["module_qualified_name"] == "com.beta.UserService.load"
    assert selected["symbol_identity"]["path"].endswith("com/beta/UserService.java")


def test_overload_group_is_ambiguous_without_signature_and_resolves_by_arity():
    index = _index()
    ambiguous = index.inspect("com.alpha.UserService.load")
    resolved = index.inspect("com.alpha.UserService.load(String,int)")

    assert ambiguous["resolution"]["status"] == "ambiguous"
    assert ambiguous["resolution"]["overload_group_id"].startswith("overload_")
    assert len(ambiguous["resolution"]["candidates"]) == 2
    assert resolved["resolution"]["status"] == "resolved"
    assert "int retry" in resolved["resolution"]["selected"]["signature"]


def test_null_lsp_is_explicit_and_callback_adapter_is_consumed():
    service = GitHubGraphService(FakeSnapshotService(), lsp_adapter=NullLspAdapter())
    unavailable = service.inspect(
        "https://github.com/openai/example",
        "src/core.loadUser",
    )

    assert unavailable["lsp"]["status"] == "unavailable"
    assert unavailable["lsp"]["provider"] == "none"

    def callback(operation: str, arguments: dict) -> dict:
        assert arguments["path"] == "src/core.ts"
        if operation == "type_info":
            return {"status": "ok", "type_text": "(id: string) => string"}
        return {
            "status": "ok",
            "locations": [{"path": "src/core.ts", "start_line": 0}],
        }

    enriched = GitHubGraphService(
        FakeSnapshotService(),
        lsp_adapter=CallbackLspAdapter("test-lsp", callback),
    ).inspect("https://github.com/openai/example", "src/core.loadUser")

    assert enriched["lsp"]["status"] == "available"
    assert enriched["lsp"]["provider"] == "test-lsp"
    assert enriched["lsp"]["type_info"]["type_text"] == "(id: string) => string"


def test_structure_quality_metrics_cover_resolution_and_impact():
    metrics = evaluate_structure_quality(
        _index(),
        resolution_cases=[
            ResolutionGoldenCase(
                "src/core.loadUser",
                "resolved",
                expected_path="src/core.ts",
                expected_qualified_name="loadUser",
            ),
            ResolutionGoldenCase("loadUser", "ambiguous"),
            ResolutionGoldenCase("doesNotExist", "unresolved"),
        ],
        impact_cases=[
            ImpactGoldenCase(
                "src/core.loadUser",
                expected_files=("src/core.ts", "src/app.ts"),
                expected_tests=("src/app.test.ts",),
            )
        ],
    )

    assert metrics["resolved_accuracy"] == 1.0
    assert metrics["ambiguous_recall"] == 1.0
    assert metrics["unresolved_recall"] == 1.0
    assert metrics["impact_file_recall"] == 1.0
    assert metrics["test_mapping_recall"] == 1.0
