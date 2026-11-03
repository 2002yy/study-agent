import json

import pytest

from src.context_builder import build_messages
from src.interactive_history import (
    INTERACTIVE_CAPABILITY_MARKER,
    compress_interactive_history,
    find_interactive_versions,
)
from src.mode_manager import RuntimeModes


def block(payload, marker="```", language="study-ui"):
    raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"{marker}{language}\n{raw}\n{marker}"


def card(identifier="java-reference", revision=1, html="<div>v</div>", **extra):
    payload = {
        "type": "interactive",
        "id": identifier,
        "revision": revision,
        "title": extra.pop("title", "Java 引用关系"),
        "summary": extra.pop("summary", "引用共享与重新赋值实验"),
        "html": html,
    }
    payload.update(extra)
    return payload


def assistant(content):
    return {"role": "assistant", "content": content}


def user(content):
    return {"role": "user", "content": content}


def big(label):
    return f"<div>{label}</div>" + "x" * 1200


def history_with_versions(*revisions, identifier="java-reference"):
    messages = []
    for revision in revisions:
        messages.append(user(f"第 {revision} 轮修改要求"))
        messages.append(
            assistant(
                f"第 {revision} 轮说明。\n\n"
                + block(
                    card(
                        identifier,
                        revision,
                        html=f"<div>rv{revision}</div>" + "x" * 1500,
                    )
                )
            )
        )
    return messages


def test_superseded_versions_become_summaries_and_the_current_one_stays():
    messages = history_with_versions(1, 2, 3)

    result = compress_interactive_history(messages, user_input="再加一步回退")

    assert result.report["status"] == "compressed"
    assert result.report["target_id"] == "java-reference"
    assert result.report["target_revision"] == 3
    current = result.messages[-1]["content"]
    assert "<div>rv3</div>" in current
    assert "```study-ui" in current
    for superseded in result.messages[1]["content"], result.messages[3]["content"]:
        assert "<div>rv1</div>" not in superseded
        assert "<div>rv2</div>" not in superseded
        assert "已被后续版本替代" in superseded
        assert "完整源码未提供" in superseded
    assert result.report["chars_removed"] > 0
    assert result.report["chars_after"] < result.report["chars_before"]


def test_stored_history_is_not_mutated():
    messages = history_with_versions(1, 2)
    snapshot = json.loads(json.dumps(messages))

    compress_interactive_history(messages, user_input="修改")

    assert messages == snapshot
    assert "<div>rv1</div>" in messages[1]["content"]


def test_stub_keeps_only_recorded_facts_and_never_claims_what_changed():
    messages = history_with_versions(1, 2)

    result = compress_interactive_history(messages, user_input="修改")
    stub = result.messages[1]["content"]

    assert "id: java-reference" in stub
    assert "revision: 1" in stub
    assert "title: Java 引用关系" in stub
    assert "summary: 引用共享与重新赋值实验" in stub
    assert "修复" not in stub
    assert "修正" not in stub
    assert result.report["removed_fields"] == ["html"]


def test_user_messages_are_never_rewritten_even_when_they_hold_a_component():
    messages = [
        user("这是我的示例：\n" + block(card("pasted", 1, html="<b>user</b>"))),
        assistant(block(card("java-reference", 1, html="<div>rv1</div>"))),
        user("改一下"),
        assistant(block(card("java-reference", 2, html="<div>rv2</div>"))),
    ]
    original = json.loads(json.dumps(messages))

    result = compress_interactive_history(messages, user_input="继续")

    assert result.messages[0] == original[0]
    assert result.messages[2] == original[2]


def test_unparseable_or_incomplete_blocks_are_left_alone():
    broken_json = "```study-ui\n{not json}\n```"
    missing_revision = block({"type": "interactive", "id": "x", "html": "<i>x</i>"})
    no_html = block(card("x", 1, html="   "))
    unclosed = "```study-ui\n" + json.dumps(card("java-reference", 1))
    non_interactive = block({"type": "chart", "title": "图", "points": []})
    messages = [
        assistant(broken_json + "\n" + missing_revision + "\n" + no_html),
        assistant(unclosed),
        assistant(non_interactive),
        assistant(block(card("java-reference", 1, html="<div>rv1</div>"))),
        assistant(block(card("java-reference", 2, html="<div>rv2</div>"))),
    ]
    original = json.loads(json.dumps(messages))

    result = compress_interactive_history(messages, user_input="继续")

    assert result.messages[0]["content"] == original[0]["content"]
    assert result.messages[1]["content"] == original[1]["content"]
    assert result.messages[2]["content"] == original[2]["content"]
    assert find_interactive_versions(messages)[0].revision == 1


def test_crlf_history_is_compressed_without_rewriting_line_endings_elsewhere():
    content = (
        "第一段\r\n\r\n"
        + block(card("java-reference", 1, html="<div>rv1</div>" + "x" * 1200)).replace("\n", "\r\n")
        + "\r\n\r\n结束\r\n"
    )
    messages = [
        user("生成"),
        assistant(content),
        user("改"),
        assistant(block(card("java-reference", 2, html="<div>rv2</div>" + "x" * 1200))),
    ]

    result = compress_interactive_history(messages, user_input="继续")
    rewritten = result.messages[1]["content"]

    assert "第一段\r\n" in rewritten
    assert "结束\r\n" in rewritten
    assert "rv1" not in rewritten
    assert "已被后续版本替代" in rewritten


def test_tilde_fences_are_recognised_and_short_closers_are_not():
    messages = [
        assistant(
            block(
                card("java-reference", 1, html="<div>rv1</div>" + "x" * 1200),
                marker="~~~",
            )
        ),
        assistant(block(card("java-reference", 2, html="<div>rv2</div>" + "x" * 1200))),
    ]

    result = compress_interactive_history(messages, user_input="继续")

    assert "rv1" not in result.messages[0]["content"]
    assert "rv2" in result.messages[1]["content"]


def test_the_follow_up_button_identifies_the_component_and_its_revision():
    messages = history_with_versions(1, 2, 3)
    follow_up = "继续探索「Java 引用关系」（版本 2）。\n当前参数与观察：{}"

    result = compress_interactive_history(messages, user_input=follow_up)

    assert result.report["reason"] == "followup_title"
    assert result.report["target_revision"] == 2
    assert "<div>rv2</div>" in result.messages[3]["content"]
    assert "rv1" not in result.messages[1]["content"]
    # Revision 3 is newer than the one the learner reopened, so it is not
    # "superseded by V2" and its source stays available.
    assert "<div>rv3</div>" in result.messages[5]["content"]
    assert [item["revision"] for item in result.report["stubbed_revisions"]] == [1]


def test_same_title_and_revision_under_two_ids_stays_untouched():
    messages = [
        assistant(block(card("stock-lock-lab", 1, html=big("a1")))),
        assistant(block(card("inventory-lock-lab", 2, html=big("b2")))),
        assistant(block(card("stock-lock-lab", 2, html=big("a2")))),
    ]
    original = json.loads(json.dumps(messages))
    follow_up = "继续探索「Java 引用关系」（版本 2）。"

    result = compress_interactive_history(messages, user_input=follow_up)

    # Two ids answer to the same title and revision, so no source may be hidden.
    assert result.report["status"] == "unresolved_target"
    assert result.report["reason"] == "ambiguous_target"
    assert result.messages == original


def test_same_title_is_disambiguated_by_the_named_revision():
    messages = [
        assistant(block(card("stock-lock-lab", 1, html=big("a1")))),
        assistant(block(card("inventory-lock-lab", 2, html=big("b2")))),
    ]
    follow_up = "继续探索「Java 引用关系」（版本 1）。"

    result = compress_interactive_history(messages, user_input=follow_up)

    assert result.report["target_id"] == "stock-lock-lab"
    assert result.report["target_revision"] == 1
    assert result.report["status"] == "nothing_superseded"
    assert "b2" in result.messages[1]["content"]


def test_a_named_revision_missing_from_the_window_compresses_nothing():
    messages = history_with_versions(1, 2)
    original = json.loads(json.dumps(messages))
    follow_up = "继续探索「Java 引用关系」（版本 5）。"

    result = compress_interactive_history(messages, user_input=follow_up)

    assert result.report["reason"] == "referenced_revision_missing"
    assert result.messages == original


def test_several_components_without_a_clear_selection_compress_nothing():
    messages = [
        assistant(block(card("java-reference", 1, html="<div>a1</div>"))),
        assistant(block(card("spring", 1, html="<div>b1</div>"))),
        assistant(block(card("java-reference", 2, html="<div>a2</div>"))),
    ]
    original = json.loads(json.dumps(messages))

    result = compress_interactive_history(messages, user_input="把颜色改深一点")

    assert result.report["status"] == "unresolved_target"
    assert result.report["reason"] == "ambiguous_multiple_ids"
    assert result.messages == original


def test_explicit_target_id_selects_the_component_the_learner_edits():
    messages = [
        assistant(block(card("java-reference", 1, html=big("a1")))),
        assistant(block(card("spring", 1, html=big("b1")))),
        assistant(block(card("java-reference", 2, html=big("a2")))),
    ]

    result = compress_interactive_history(
        messages, user_input="调整一下", target_id="java-reference"
    )

    assert result.report["reason"] == "explicit_id"
    assert "a1" not in result.messages[0]["content"]
    assert "b1" in result.messages[1]["content"]
    assert "a2" in result.messages[2]["content"]
    assert result.report["untouched_ids"] == ["spring"]


def test_other_components_keep_their_source():
    messages = [
        assistant(block(card("java-reference", 1, html=big("a1")))),
        assistant(block(card("spring", 1, html=big("b1")))),
        assistant(block(card("java-reference", 2, html=big("a2")))),
        assistant(block(card("spring", 2, html=big("b2")))),
    ]

    result = compress_interactive_history(
        messages, user_input="继续", target_id="java-reference"
    )

    assert "b1" in result.messages[1]["content"]
    assert "b2" in result.messages[3]["content"]
    assert "a1" not in result.messages[0]["content"]


def test_a_study_ui_example_inside_a_plain_code_fence_is_documentation():
    inner = block(card("demo", 1, html=big("demo")))
    messages = [
        assistant("````markdown\n" + inner + "\n````"),
        assistant(block(card("demo", 2, html=big("real")))),
    ]
    original = json.loads(json.dumps(messages))

    result = compress_interactive_history(messages, user_input="继续")

    # The nested example is not a running component, so only v2 is a version
    # and there is nothing older to compress.
    assert [item.revision for item in find_interactive_versions(messages)] == [2]
    assert result.report["status"] == "nothing_superseded"
    assert result.messages == original


@pytest.mark.parametrize(
    "payload",
    [
        {**card(), "id": "has space"},
        {**card(), "id": "中文标识"},
        {**card(), "id": "x" * 65},
        {**card(), "revision": 0},
        {**card(), "revision": 1000},
        {**card(), "revision": True},
        {**card(), "html": "x" * 60001},
        {key: value for key, value in card().items() if key != "summary"},
        {**card(), "title": "  "},
    ],
)
def test_fields_the_browser_rejects_are_not_versions(payload):
    messages = [
        assistant(block(payload)),
        assistant(block(card("java-reference", 2, html=big("v2")))),
    ]

    assert [item.revision for item in find_interactive_versions(messages)] == [2]


def test_an_oversized_block_is_not_a_version():
    payload = {**card(), "html": "x" * 59990, "notes": "y" * 40000}
    messages = [
        assistant(block(payload)),
        assistant(block(card("java-reference", 2, html=big("v2")))),
    ]

    assert [item.revision for item in find_interactive_versions(messages)] == [2]


def test_capability_marker_gates_the_rewrite():
    messages = history_with_versions(1, 2)

    result = compress_interactive_history(
        messages, user_input="继续", capability_enabled=False
    )

    assert result.report["status"] == "unchanged"
    assert result.report["reason"] == "capability_not_declared"
    assert result.messages == messages


def test_compression_is_idempotent():
    messages = history_with_versions(1, 2, 3)

    first = compress_interactive_history(messages, user_input="继续")
    second = compress_interactive_history(first.messages, user_input="继续")

    assert second.report["status"] == "nothing_superseded"
    assert second.messages == first.messages


def test_single_version_history_needs_no_rewrite():
    messages = history_with_versions(1)

    result = compress_interactive_history(messages, user_input="继续")

    assert result.report["status"] == "nothing_superseded"
    assert result.messages == messages


def test_a_document_smaller_than_its_summary_is_kept_as_written():
    messages = [
        assistant(block(card("java-reference", 1, html="<i>x</i>"))),
        assistant(block(card("java-reference", 2, html=big("y")))),
        assistant(block(card("java-reference", 3, html=big("z")))),
    ]

    result = compress_interactive_history(messages, user_input="继续")

    assert result.report["status"] == "compressed"
    assert [item["revision"] for item in result.report["stubbed_revisions"]] == [2]
    assert "<i>x</i>" in result.messages[0]["content"]
    assert big("z") in result.messages[2]["content"]


def test_empty_history_is_returned_untouched():
    result = compress_interactive_history([], user_input="继续")

    assert result.messages == []
    assert result.report["reason"] == "empty_history"


def test_build_messages_compresses_only_when_the_ui_capability_is_declared():
    messages = history_with_versions(1, 2)

    with_capability = build_messages(
        "再加一步回退",
        role_prompt="角色",
        mode="普通",
        memory_bundle={},
        chat_history=messages,
        runtime_modes=RuntimeModes(),
        conversation_instruction=INTERACTIVE_CAPABILITY_MARKER,
    )
    without = build_messages(
        "再加一步回退",
        role_prompt="角色",
        mode="普通",
        memory_bundle={},
        chat_history=messages,
        runtime_modes=RuntimeModes(),
    )

    assert "<div>rv1</div>" not in with_capability[2]["content"]
    assert "<div>rv2</div>" in with_capability[4]["content"]
    assert "<div>rv1</div>" in without[2]["content"]
