from pathlib import Path
from tools.package_project_helper import should_exclude


def test_fastapi_api_is_modular_package():
    assert Path("src/api").is_dir()
    assert Path("src/api/app.py").is_file()
    assert Path("src/api/routes/chat_routes.py").is_file()
    assert Path("src/api/routes/session_routes.py").is_file()
    assert not Path("src/api.py").exists()


def test_application_helpers_paths_stay_at_project_root():
    from src.application import helpers

    root = Path.cwd().resolve()
    assert helpers.ROOT.resolve() == root
    assert helpers.FRONTEND_SETTINGS_PATH_DEFAULT.resolve() == root / "config" / "frontend_settings.yaml"
    assert helpers.SESSION_DIR_DEFAULT.resolve() == root / "logs" / "sessions"


def test_sidebar_save_uses_session_id():
    text = Path("src/ui/sidebar.py").read_text(encoding="utf-8")
    assert "save(st.session_state.session_id)" in text
    assert "path = save()" not in text


def test_wechat_panel_no_duplicate_render_call():
    text = Path("src/ui/wechat_panel.py").read_text(encoding="utf-8")
    needle = "_render_wechat_stream(content_placeholder, content)\n    _render_wechat_stream(content_placeholder, content)"
    assert needle not in text


def test_env_variants_are_excluded():
    assert should_exclude(Path(".ENV"))
    assert should_exclude(Path(".env.LOCAL"))
    assert should_exclude(Path(".env.production"))
    assert should_exclude(Path(".env.backup"))
    assert not should_exclude(Path(".env.example"))


def test_zip_variants_are_excluded():
    assert should_exclude(Path("abc.ZIP"))
    assert should_exclude(Path("abc.zip"))


def test_chat_archive_is_excluded():
    assert should_exclude(Path("chat/archive/a.md"))


def test_docx_is_excluded():
    assert should_exclude(Path("docs/agent_core_roles.docx"))


def test_python_cache_are_excluded():
    assert should_exclude(Path("src/module.pyc"))
    assert should_exclude(Path("src/module.pyo"))


def test_binary_images_are_not_excluded_by_name():
    assert not should_exclude(Path("assets/avatars/march7.png"))


def test_package_script_has_python_fallback_candidates():
    text = Path("tools/package_project.ps1").read_text(encoding="utf-8")
    assert '$candidates = @("python", "py", "python3")' in text
    assert '$result = & $PythonCmd $HelperScript $Root $OutputZip $includeTestsFlag 2>&1' in text


def test_package_helper_required_files_are_locked():
    text = Path("tools/package_project_helper.py").read_text(encoding="utf-8")
    assert '"src/ui/wechat_panel.py"' in text
    assert '"src/safe_writer.py"' in text
    assert '"src/mode_manager.py"' in text
    assert '"src/llm_client.py"' in text
    assert '"tools/package_project.ps1"' in text
    assert '"tools/package_project_helper.py"' in text
    assert 'missing = [item for item in required if item not in names]' in text


def test_package_helper_module_guards_main():
    text = Path("tools/package_project_helper.py").read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in text


def test_health_check_does_not_create_runtime_dirs():
    text = Path("src/health_check.py").read_text(encoding="utf-8")
    assert "path.mkdir(parents=True, exist_ok=True)" not in text
    assert "os.access(probe, os.W_OK)" in text


def test_opening_radio_does_not_immediately_write_interaction_mode():
    text = Path("src/ui/wechat_panel.py").read_text(encoding="utf-8")
    assert "def _commit_interaction_mode(choice: str):" in text
    # The interaction_mode write must only live inside _commit_interaction_mode,
    # not directly in _render_opening_setup
    count = text.count("if choice != st.session_state.interaction_mode:")
    assert count == 1, f"Expected 1 occurrence, found {count}"


def test_tmp_files_are_excluded():
    assert should_exclude(Path("chat/wechat_state.md.20260508_150258_825985.tmp"))
    assert should_exclude(Path("memory/internal_state.md.tmp"))


def test_global_state_buttons_use_app_rerun():
    text = Path("src/ui/wechat_panel.py").read_text(encoding="utf-8")
    assert 'key="mark_wechat_read"' in text
    assert 'key="new_wechat_group"' in text
    assert 'key="news_round_button"' in text
    assert "_rerun_app()" in text


def test_wechat_join_state_uses_single_batch_write():
    text = Path("src/mode_manager.py").read_text(encoding="utf-8")
    assert "def _write_keyvalues" in text
    assert "_write_keyvalues(" in text
    assert 'user_has_joined_group": "true" if user_has_joined else "false"' in text


def test_llm_client_can_reset_cached_client():
    text = Path("src/llm_client.py").read_text(encoding="utf-8")
    assert "def reset_client()" in text
    assert "_client_signature" in text

    config_text = Path("src/config.py").read_text(encoding="utf-8")
    assert "reset_client" in config_text


def test_exports_are_excluded():
    assert should_exclude(Path("exports/session_report_20260508.md"))
    assert should_exclude(Path("exports/session_report_20260508.docx"))


def test_replacement_artifact_dirs_are_excluded():
    assert should_exclude(Path("article_text_replacement_files_v069/src/wechat.py"))
    assert should_exclude(Path("article_text_replacement_files_v070/src/ui/wechat_panel.py"))


def test_session_logger_init_does_not_create_dirs():
    text = Path("src/session_logger.py").read_text(encoding="utf-8")
    block_start = text.index("def init_session()")
    block_end = text.index("def get_or_create_session")
    block = text[block_start:block_end]
    assert "_ensure_dir()" not in block


def test_session_logger_get_or_create_does_not_create_dirs():
    text = Path("src/session_logger.py").read_text(encoding="utf-8")
    block_start = text.index("def get_or_create_session")
    block_end = text.index("def set_after_session_status")
    block = text[block_start:block_end]
    assert "_ensure_dir()" not in block


def test_session_logger_flush_uses_safe_writer():
    text = Path("src/session_logger.py").read_text(encoding="utf-8")
    block_start = text.index("def flush_current_session")
    block_end = text.index("def save(")
    block = text[block_start:block_end]
    assert "safe_write_text(current_file, existing + chunk)" in block
    assert "with current_file.open(" not in block


def test_chat_and_session_routes_use_application_services_only():
    chat_route = Path("src/api/routes/chat_routes.py").read_text(encoding="utf-8")
    session_route = Path("src/api/routes/session_routes.py").read_text(encoding="utf-8")

    for route in (chat_route, session_route):
        assert "from src.api import" not in route
        assert "src.session_logger" not in route
        assert "src.llm_client" not in route
    assert "ChatService" in chat_route
    assert "SessionService" in session_route


def test_chat_service_does_not_depend_on_api_package():
    text = Path("src/application/chat_service.py").read_text(encoding="utf-8")
    assert "from src.api" not in text
    assert "import src.api" not in text


def test_frontend_chat_state_is_owned_by_workspace_provider():
    app_text = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    main_text = Path("frontend/src/main.tsx").read_text(encoding="utf-8")

    assert "<WorkspaceProvider" in main_text
    assert "useChatController()" in app_text
    assert "useState<ChatMessage[]" not in app_text
    assert "useState<ChatResponse" not in app_text
    assert "useReducer(workspaceReducer" not in app_text


def test_sidebar_force_refresh_clears_memory_cache():
    text = Path("src/ui/sidebar.py").read_text(encoding="utf-8")
    assert 'st.session_state.memory_bundle = {}' in text
    assert 'st.session_state.memory_context_mode = ""' in text


def test_runtime_version_is_synced():
    mode_text = Path("src/mode_manager.py").read_text(encoding="utf-8")
    state_text = Path("memory/internal_state.md").read_text(encoding="utf-8")
    yaml_text = Path("config/runtime_state.yaml").read_text(encoding="utf-8")

    assert 'current_version: str = "v0.8.0"' in mode_text
    assert 'next_version: str = "v0.8.1"' in mode_text
    assert '- current_version: v0.8.0' in state_text
    assert '- next_version: v0.8.1' in state_text
    assert "current: v0.8.0" in yaml_text
    assert "next: v0.8.1" in yaml_text


def test_ci_workflow_exists_and_runs_core_checks():
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "name: CI" in text
    assert "pull_request:" in text
    assert "push:" in text
    assert "pip install -r requirements.txt -r requirements-dev.txt" in text
    assert "pytest" in text
    assert "ruff check ." in text
    assert "Run expanded mypy" in text
    assert "mypy --explicit-package-bases src/" in text
    assert "Run package helper" in text
    assert "detect-secrets" in text


def test_ci_secret_scan_fails_on_any_detect_secrets_finding():
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "json.load(f)" in text
    assert 'report.get("results", {})' in text
    assert "if findings:" in text
    assert '"is_secret": true' not in text
