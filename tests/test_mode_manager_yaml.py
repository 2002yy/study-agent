import yaml

from src import mode_manager


def _clear_mode_cache():
    try:
        mode_manager.load_runtime_config.clear()
        mode_manager.load_runtime_modes.clear()
    except Exception:
        pass


def test_load_runtime_modes_reads_yaml_state(monkeypatch, tmp_path):
    runtime_state = tmp_path / "config" / "runtime_state.yaml"
    internal_state = tmp_path / "memory" / "internal_state.md"
    interaction_settings = tmp_path / "memory" / "interaction_settings.md"
    wechat_state = tmp_path / "chat" / "wechat_state.md"
    runtime_state.parent.mkdir(parents=True, exist_ok=True)

    runtime_state.write_text(
        yaml.safe_dump(
            {
                "version": {
                    "current": "v9.0.0",
                    "next": "v9.0.1",
                    "active_task": "yaml state task",
                },
                "runtime": {
                    "entry_mode": "single",
                    "performance_mode": "deep",
                    "route_mode": "hybrid",
                    "memory_mode": "locked",
                    "debug_mode": True,
                    "safe_mode": True,
                },
                "interaction": {
                    "relationship_mode": "warm",
                },
                "wechat": {
                    "mode": "interactive_group",
                    "user_has_joined_group": True,
                    "first_join_reaction_done": True,
                    "memory_capture_enabled": True,
                    "memory_capture_mode": "auto",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(mode_manager, "RUNTIME_STATE", runtime_state)
    monkeypatch.setattr(mode_manager, "INTERNAL_STATE", internal_state)
    monkeypatch.setattr(mode_manager, "INTERACTION_SETTINGS", interaction_settings)
    monkeypatch.setattr(mode_manager, "WECHAT_STATE", wechat_state)
    _clear_mode_cache()

    modes = mode_manager.load_runtime_modes()

    assert modes.current_version == "v9.0.0"
    assert modes.next_version == "v9.0.1"
    assert modes.active_task == "yaml state task"
    assert modes.entry_mode == "single"
    assert modes.performance_mode == "deep"
    assert modes.route_mode == "hybrid"
    assert modes.memory_mode == "locked"
    assert modes.debug_mode is True
    assert modes.safe_mode is True
    assert modes.relationship_mode == "warm"
    assert modes.wechat_mode == "interactive_group"
    assert modes.user_has_joined is True
    assert modes.first_reaction_done is True
    assert modes.memory_capture_enabled is True
    assert modes.memory_capture_mode == "auto"


def test_missing_yaml_migrates_from_markdown(monkeypatch, tmp_path):
    runtime_state = tmp_path / "config" / "runtime_state.yaml"
    internal_state = tmp_path / "memory" / "internal_state.md"
    interaction_settings = tmp_path / "memory" / "interaction_settings.md"
    wechat_state = tmp_path / "chat" / "wechat_state.md"
    internal_state.parent.mkdir(parents=True, exist_ok=True)
    interaction_settings.parent.mkdir(parents=True, exist_ok=True)
    wechat_state.parent.mkdir(parents=True, exist_ok=True)

    internal_state.write_text(
        "# internal\n\n"
        "- memory_mode: confirm_write\n"
        "- route_mode: hybrid\n"
        "- debug_mode: true\n"
        "- safe_mode: true\n"
        "- performance_mode: fast\n"
        "- entry_mode: single\n"
        "- current_version: v1.2.3\n"
        "- active_task: migrate me\n"
        "- next_version: v1.2.4\n",
        encoding="utf-8",
    )
    interaction_settings.write_text(
        "# interaction\n\n- relationship_mode: close\n",
        encoding="utf-8",
    )
    wechat_state.write_text(
        "# wechat\n\n"
        "- user_has_joined_group: true\n"
        "- first_join_reaction_done: false\n"
        "- mode: first_user_join\n"
        "- memory_capture_enabled: true\n"
        "- memory_capture_mode: manual\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mode_manager, "RUNTIME_STATE", runtime_state)
    monkeypatch.setattr(mode_manager, "INTERNAL_STATE", internal_state)
    monkeypatch.setattr(mode_manager, "INTERACTION_SETTINGS", interaction_settings)
    monkeypatch.setattr(mode_manager, "WECHAT_STATE", wechat_state)
    _clear_mode_cache()

    modes = mode_manager.load_runtime_modes()

    assert runtime_state.exists()
    assert modes.memory_mode == "confirm_write"
    assert modes.route_mode == "hybrid"
    assert modes.debug_mode is True
    assert modes.safe_mode is True
    assert modes.performance_mode == "fast"
    assert modes.entry_mode == "single"
    assert modes.current_version == "v1.2.3"
    assert modes.next_version == "v1.2.4"
    assert modes.active_task == "migrate me"
    assert modes.relationship_mode == "close"
    assert modes.wechat_mode == "first_user_join"
    assert modes.user_has_joined is True
    assert modes.first_reaction_done is False
    assert modes.memory_capture_enabled is True


def test_updates_write_yaml_and_sync_markdown(monkeypatch, tmp_path):
    runtime_state = tmp_path / "config" / "runtime_state.yaml"
    internal_state = tmp_path / "memory" / "internal_state.md"
    interaction_settings = tmp_path / "memory" / "interaction_settings.md"
    wechat_state = tmp_path / "chat" / "wechat_state.md"
    runtime_state.parent.mkdir(parents=True, exist_ok=True)
    runtime_state.write_text(
        yaml.safe_dump(mode_manager._default_runtime_state_dict(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(mode_manager, "RUNTIME_STATE", runtime_state)
    monkeypatch.setattr(mode_manager, "INTERNAL_STATE", internal_state)
    monkeypatch.setattr(mode_manager, "INTERACTION_SETTINGS", interaction_settings)
    monkeypatch.setattr(mode_manager, "WECHAT_STATE", wechat_state)
    _clear_mode_cache()

    mode_manager.update_entry_mode("single")
    mode_manager.update_interaction_mode("warm")
    mode_manager.update_wechat_join_state(True, True, "interactive_group")

    state = yaml.safe_load(runtime_state.read_text(encoding="utf-8"))
    assert state["runtime"]["entry_mode"] == "single"
    assert state["interaction"]["relationship_mode"] == "warm"
    assert state["wechat"]["user_has_joined_group"] is True
    assert state["wechat"]["first_join_reaction_done"] is True

    assert "- entry_mode: single" in internal_state.read_text(encoding="utf-8")
    assert "- relationship_mode: warm" in interaction_settings.read_text(encoding="utf-8")
    wechat_text = wechat_state.read_text(encoding="utf-8")
    assert "- user_has_joined_group: true" in wechat_text
    assert "- first_join_reaction_done: true" in wechat_text


def test_yaml_remains_source_of_truth_when_markdown_drifts(monkeypatch, tmp_path):
    runtime_state = tmp_path / "config" / "runtime_state.yaml"
    internal_state = tmp_path / "memory" / "internal_state.md"
    interaction_settings = tmp_path / "memory" / "interaction_settings.md"
    wechat_state = tmp_path / "chat" / "wechat_state.md"
    runtime_state.parent.mkdir(parents=True, exist_ok=True)
    internal_state.parent.mkdir(parents=True, exist_ok=True)
    interaction_settings.parent.mkdir(parents=True, exist_ok=True)
    wechat_state.parent.mkdir(parents=True, exist_ok=True)

    runtime_state.write_text(
        yaml.safe_dump(
            {
                "version": {
                    "current": "v0.7.5",
                    "next": "v0.7.6",
                    "active_task": "yaml source",
                },
                "runtime": {
                    "entry_mode": "wechat",
                    "performance_mode": "standard",
                    "route_mode": "auto_rule",
                    "memory_mode": "preview",
                    "debug_mode": False,
                    "safe_mode": False,
                },
                "interaction": {
                    "relationship_mode": "close",
                },
                "wechat": {
                    "mode": "unread_feedback",
                    "user_has_joined_group": False,
                    "first_join_reaction_done": False,
                    "memory_capture_enabled": True,
                    "memory_capture_mode": "manual",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    internal_state.write_text("# stale\n- entry_mode: single\n", encoding="utf-8")
    interaction_settings.write_text(
        "# stale\n- relationship_mode: warm\n",
        encoding="utf-8",
    )
    wechat_state.write_text(
        "# stale\n- mode: interactive_group\n- first_join_reaction_done: true\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mode_manager, "RUNTIME_STATE", runtime_state)
    monkeypatch.setattr(mode_manager, "INTERNAL_STATE", internal_state)
    monkeypatch.setattr(mode_manager, "INTERACTION_SETTINGS", interaction_settings)
    monkeypatch.setattr(mode_manager, "WECHAT_STATE", wechat_state)
    _clear_mode_cache()

    modes = mode_manager.load_runtime_modes()

    assert modes.wechat_mode == "unread_feedback"
    assert modes.first_reaction_done is False
    assert "- entry_mode: wechat" in internal_state.read_text(encoding="utf-8")
    assert "- relationship_mode: close" in interaction_settings.read_text(encoding="utf-8")
    wechat_text = wechat_state.read_text(encoding="utf-8")
    assert "- mode: unread_feedback" in wechat_text
    assert "- first_join_reaction_done: false" in wechat_text


def test_runtime_config_schema_warns_and_uses_safe_defaults(monkeypatch, tmp_path):
    runtime_state = tmp_path / "config" / "runtime_state.yaml"
    internal_state = tmp_path / "memory" / "internal_state.md"
    interaction_settings = tmp_path / "memory" / "interaction_settings.md"
    wechat_state = tmp_path / "chat" / "wechat_state.md"
    runtime_state.parent.mkdir(parents=True, exist_ok=True)

    raw_state = mode_manager._default_runtime_state_dict()
    raw_state["runtime"]["entry_mode"] = "desktop"
    raw_state["runtime"]["debug_mode"] = "true"
    raw_state["runtime"]["typo_mode"] = "oops"
    raw_state["wechat"]["memory_capture_enabled"] = "not-bool"
    raw_state["unknown"] = {"x": 1}
    runtime_state.write_text(
        yaml.safe_dump(raw_state, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(mode_manager, "RUNTIME_STATE", runtime_state)
    monkeypatch.setattr(mode_manager, "INTERNAL_STATE", internal_state)
    monkeypatch.setattr(mode_manager, "INTERACTION_SETTINGS", interaction_settings)
    monkeypatch.setattr(mode_manager, "WECHAT_STATE", wechat_state)
    _clear_mode_cache()

    result = mode_manager.load_runtime_config()
    modes = mode_manager.load_runtime_modes()

    assert modes.entry_mode == "wechat"
    assert modes.debug_mode is True
    assert modes.memory_capture_enabled is False
    assert any("runtime.entry_mode: invalid value" in item for item in result.warnings)
    assert any("runtime.debug_mode: coerced string boolean" in item for item in result.warnings)
    assert any("runtime.typo_mode: unknown key ignored" in item for item in result.warnings)
    assert any("unknown: unknown section ignored" in item for item in result.warnings)


def test_runtime_config_invalid_yaml_returns_defaults_with_warning(monkeypatch, tmp_path):
    runtime_state = tmp_path / "config" / "runtime_state.yaml"
    internal_state = tmp_path / "memory" / "internal_state.md"
    interaction_settings = tmp_path / "memory" / "interaction_settings.md"
    wechat_state = tmp_path / "chat" / "wechat_state.md"
    runtime_state.parent.mkdir(parents=True, exist_ok=True)
    runtime_state.write_text("runtime: [broken", encoding="utf-8")

    monkeypatch.setattr(mode_manager, "RUNTIME_STATE", runtime_state)
    monkeypatch.setattr(mode_manager, "INTERNAL_STATE", internal_state)
    monkeypatch.setattr(mode_manager, "INTERACTION_SETTINGS", interaction_settings)
    monkeypatch.setattr(mode_manager, "WECHAT_STATE", wechat_state)
    _clear_mode_cache()

    result = mode_manager.load_runtime_config()

    assert result.state["runtime"]["entry_mode"] == "wechat"
    assert any("failed to parse YAML" in item for item in result.warnings)
