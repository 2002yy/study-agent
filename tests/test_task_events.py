from src.mode_manager import RuntimeModes


def test_memory_writer_emits_failed_event_when_permission_denied(monkeypatch):
    from src import memory_writer

    events = []

    monkeypatch.setattr(
        memory_writer,
        "load_runtime_modes",
        lambda: RuntimeModes(memory_mode="locked", safe_mode=False),
    )

    result = memory_writer.append_memory(
        "progress",
        "content",
        event_callback=events.append,
    )

    assert result.startswith("[")
    assert [event.event_type for event in events] == ["started", "failed"]
    assert events[-1].data["target"] == "progress"


def test_memory_writer_emits_completed_event_for_success(monkeypatch, tmp_path):
    from src import memory_writer

    events = []
    target = tmp_path / "progress.md"

    monkeypatch.setattr(
        memory_writer,
        "load_runtime_modes",
        lambda: RuntimeModes(memory_mode="confirm_write", safe_mode=False),
    )
    monkeypatch.setitem(memory_writer.MEMORY_TARGETS, "progress", target)

    result = memory_writer.append_memory(
        "progress",
        "content",
        event_callback=events.append,
    )

    assert result == str(target)
    assert target.exists()
    assert [event.event_type for event in events] == ["started", "completed"]
    assert events[-1].data["path"] == str(target)
