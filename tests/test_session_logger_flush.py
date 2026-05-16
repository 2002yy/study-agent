import pytest

from src import session_logger


@pytest.fixture(autouse=True)
def _isolated_logger_state(monkeypatch, tmp_path):
    monkeypatch.setattr(session_logger, "CURRENT_DIR", tmp_path / "current")
    monkeypatch.setattr(session_logger, "LOG_DIR", tmp_path / "sessions")
    session_logger._state.clear()
    yield
    session_logger._state.clear()


@pytest.mark.parametrize(
    ("performance_mode", "debug_mode", "flush_results"),
    [
        ("fast", False, [False, False, False, True]),
        ("standard", False, [False, True]),
        ("deep", False, [False, True]),
        ("fast", True, [True, True]),
    ],
)
def test_flush_current_session_batches_by_mode(
    performance_mode,
    debug_mode,
    flush_results,
):
    session_id = session_logger.init_session()

    observed = []
    for idx, expected in enumerate(flush_results, start=1):
        session_logger.log(
            session_id,
            role="march7",
            mode="chat",
            model="flash",
            user_input=f"u{idx}",
            agent_reply=f"a{idx}",
        )
        flushed = session_logger.flush_current_session(
            session_id,
            performance_mode=performance_mode,
            debug_mode=debug_mode,
        )
        observed.append(flushed)
        assert flushed is expected

    current_file = session_logger.CURRENT_DIR / f"{session_id}.md"
    assert current_file.exists()
    text = current_file.read_text(encoding="utf-8")
    assert "User: u1" in text
    assert f"Agent: a{len(flush_results)}" in text
    assert observed == flush_results


def test_save_forces_pending_entries_flush():
    session_id = session_logger.init_session()
    session_logger.log(
        session_id,
        role="march7",
        mode="chat",
        model="flash",
        user_input="u1",
        agent_reply="a1",
    )

    saved_path = session_logger.save(session_id)

    assert saved_path
    assert session_logger._state[session_id]["entries"] == []
    assert session_logger._state[session_id]["flushed_count"] == 0
    assert not (session_logger.CURRENT_DIR / f"{session_id}.md").exists()
