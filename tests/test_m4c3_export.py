import hashlib
import json
import sqlite3

import pytest

from tools.m4c3_export import export_raw
from tools.interactive_replay_export import collect


def test_export_preserves_raw_html_and_requires_explicit_mapping(tmp_path):
    db_path = tmp_path / "runtime.db"
    raw = "<main>原始页面</main><script>window.studyUI.setState({x:1})</script>"
    payload = dict(
        type="interactive",
        id="../../unsafe-name",
        revision=1,
        title="Example",
        summary="test",
        html=raw,
    )
    # Use a legitimate component id; export filenames must be independent of it.
    payload["id"] = "cache-ref-canvas"
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TABLE chat_turns (thread_id TEXT,id TEXT,user_message TEXT,"
            "assistant_message TEXT,created_at TEXT,status TEXT)"
        )
        db.execute(
            "INSERT INTO chat_turns VALUES ('thread','turn','prompt',?,'now','completed')",
            ("```study-ui\n" + json.dumps(payload) + "\n```",),
        )
    out = tmp_path / "export"
    assert export_raw([db_path, db_path], out, {"cache-ref-canvas": "J01"}) == 1
    case = json.loads((out / "index.json").read_text(encoding="utf-8"))["cases"][0]
    assert (out / case["file"]).read_bytes() == raw.encode()
    assert case["sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert case["task_id"] == "J01"
    assert case["source_kind"] == "saved_model"
    assert case["capabilities"] == []
    other = tmp_path / "unmapped"
    export_raw(db_path, other, {})
    assert json.loads((other / "index.json").read_text())["cases"][0]["task_id"] is None
    with pytest.raises(FileExistsError):
        export_raw(db_path, out, {})


def test_missing_database_does_not_create_database_or_output(tmp_path):
    path, out = tmp_path / "missing.db", tmp_path / "export"
    with pytest.raises(sqlite3.OperationalError):
        export_raw(path, out, {})
    assert not path.exists()
    assert not out.exists()


def test_same_html_with_different_host_capabilities_is_not_deduplicated(tmp_path):
    path = tmp_path / "runtime.db"
    payload = dict(
        type="interactive",
        id="mesh",
        revision=1,
        title="Mesh",
        summary="example",
        html="<p>same source</p>",
    )
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE chat_turns (thread_id TEXT,id TEXT,user_message TEXT,"
            "assistant_message TEXT,created_at TEXT,status TEXT)"
        )
        for number, capabilities in enumerate(([], ["three"])):
            answer = (
                "```study-ui\n"
                + json.dumps(payload | {"capabilities": capabilities})
                + "\n```"
            )
            db.execute(
                "INSERT INTO chat_turns VALUES ('thread',?,'prompt',?,'now','completed')",
                (str(number), answer),
            )
    out = tmp_path / "export"
    assert export_raw([path, path], out, {}) == 2
    cases = json.loads((out / "index.json").read_text())["cases"]
    assert [case["capabilities"] for case in cases] == [[], ["three"]]
    assert cases[0]["sha256"] == cases[1]["sha256"]
    assert len({case["case_id"] for case in collect(path)}) == 2
