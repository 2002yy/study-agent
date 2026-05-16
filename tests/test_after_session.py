import json
from src.update_validator import validate_updates
from src.safe_writer import safe_write_text, append_text_safely
from src.after_session import _parse_json, _extract_json_braces, _build_markdown_preview


def test_generate_after_session_updates_uses_json_mode(monkeypatch):
    from src import after_session

    captured = {}

    def fake_chat(messages, **kwargs):
        captured["kwargs"] = kwargs
        return VALID_JSON

    monkeypatch.setattr(after_session, "chat", fake_chat)

    result = after_session.generate_after_session_updates(
        session_messages=[{"role": "user", "content": "hello"}],
        memory_bundle={},
        role="nahida",
        mode="普通",
        model_profile="pro",
    )

    assert result["progress_update"]
    assert captured["kwargs"]["task_name"] == "after_session"
    assert captured["kwargs"]["temperature"] is None


def test_validator_rejects_emotion():
    bad = {"learner_profile_update": "用户学习时很焦虑，缺乏耐心"}
    warnings = validate_updates(bad)
    assert len(warnings) >= 1


def test_validator_rejects_overclaim():
    bad = {"progress_update": "v0.6 已完成视觉增强，v0.7 已上线"}
    warnings = validate_updates(bad)
    assert len(warnings) >= 1


def test_validator_rejects_too_long():
    bad = {"current_focus_update": "x" * 600}
    warnings = validate_updates(bad)
    assert len(warnings) >= 1


def test_validator_accepts_good():
    good = {
        "progress_update": "- 完成v0.5路由开发",
        "learner_profile_update": "本轮无需更新",
        "current_focus_update": "优先：自动路由",
    }
    warnings = validate_updates(good)
    assert len(warnings) == 0


def test_writer_appends_safely(tmp_path):
    f = tmp_path / "test.md"
    safe_write_text(f, "# 初始\n内容 A")
    append_text_safely(f, "内容 B")
    content = f.read_text(encoding="utf-8")
    assert "初始" in content
    assert "内容 B" in content
    assert content.index("内容 A") < content.index("内容 B")


def test_writer_backups_before_overwrite(tmp_path):
    f = tmp_path / "test_cf.md"
    safe_write_text(f, "# 旧焦点")
    # backup goes to project's backups/memory_backups/, not tmp_path
    from src.safe_writer import BACKUP_DIR as B

    before = len(list(B.glob("test_cf_*.bak")))
    safe_write_text(f, "# 新焦点")
    after = len(list(B.glob("test_cf_*.bak")))
    assert after > before
    for b in B.glob("test_cf_*.bak"):
        b.unlink()


# ── Three-layer JSON parsing tests ──

VALID_JSON = json.dumps(
    {
        "progress_update": "完成路由开发",
        "learner_profile_update": "本轮无需更新",
        "current_focus_update": "优先：自动路由",
        "revision_notes_update": "本轮无需更新",
        "session_archive_update": "v0.5 已完成",
        "role_updates": {"march7": "用户状态良好", "keqing": "需要抓紧"},
    }
)


def test_layer1_strips_code_fence():
    """层1：```json...``` 包裹的 JSON 可正常解析"""
    raw = f"```json\n{VALID_JSON}\n```"
    result = _parse_json(raw)
    assert result["progress_update"] == "完成路由开发"
    assert result["session_archive_update"] == "v0.5 已完成"


def test_layer1_plain_json():
    """纯 JSON 直接解析"""
    result = _parse_json(VALID_JSON)
    assert result["progress_update"] == "完成路由开发"


def test_layer2_extract_from_middle():
    """层2：模型输出了多余解释文本，在前后夹带文字时仍能截取 {} 解析"""
    raw = f"好的，这是生成的 JSON：\n{VALID_JSON}\n希望这对你有帮助。"
    result = _parse_json(raw)
    assert result["progress_update"] == "完成路由开发"
    assert result["session_archive_update"] == "v0.5 已完成"


def test_layer2_extract_when_code_fence_and_extra():
    """层1 失败后层2 兜底：有 code fence + 多余文字"""
    raw = f"```json\n{VALID_JSON}\n```\n以上是本次更新，请确认。"
    result = _parse_json(raw)
    assert result["progress_update"] == "完成路由开发"


def test_layer2_extract_nested_braces():
    """层2：role_updates 里自带的 {} 不会干扰第一层 {}"""
    payload = {
        "progress_update": "ok",
        "role_updates": {"march7": "不错", "keqing": "加油"},
    }
    json_str = json.dumps(payload, ensure_ascii=False)
    raw = f"来啦：\n{json_str}\n收工。"
    result = _parse_json(raw)
    assert result["progress_update"] == "ok"
    assert "march7" in result["role_updates"]


def test_layer2_no_braces_returns_empty():
    """文本里完全没有 {}，返回空 dict"""
    result = _parse_json("这是一段纯文本，没有 JSON。")
    assert result == {}


def test_layer2_garbled_braces_returns_empty():
    """花括号里的内容不是合法 JSON，返回空 dict"""
    result = _parse_json("{这不是合法json}")
    assert result == {}


def test_layer3_build_preview():
    """层3：生成 markdown 预览，不包含 raw 开头/结尾的空行"""
    raw = "   \n\n第一行内容\n第二行内容\n\n   "
    preview = _build_markdown_preview(raw)
    assert "课后更新（自动解析失败" in preview
    assert "第一行内容" in preview
    assert "第二行内容" in preview
    assert preview.startswith("###")


def test_layer3_build_preview_empty():
    """空文本返回占位提示"""
    preview = _build_markdown_preview("")
    assert "无有效输出" in preview


def test_layer3_build_preview_truncates():
    """超过 40 行截断并标注"""
    lines = [f"line {i}" for i in range(50)]
    raw = "\n".join(lines)
    preview = _build_markdown_preview(raw)
    assert "line 0" in preview
    assert "line 39" in preview
    assert "line 40" not in preview
    assert "已截断" in preview
    assert "共 50 行" in preview


def test_extract_json_braces_direct():
    """_extract_json_braces 单元测试"""
    data = _extract_json_braces(f"前缀 {VALID_JSON} 后缀")
    assert data is not None
    assert data["progress_update"] == "完成路由开发"
