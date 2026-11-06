import json
from types import SimpleNamespace

from src.interactive_history import find_interactive_versions
from src.interactive_restore import (
    RestoreRequest,
    locate_restore_source,
    restore_context_block,
)
from src.interactive_patch import prepare_patch, source_hash, TextEdit


def turn(capabilities):
    card = dict(
        type="interactive",
        id="scene",
        revision=1,
        title="Scene",
        summary="A scene",
        html="<p>old</p>",
        capabilities=capabilities,
    )
    return SimpleNamespace(
        id="saved",
        status="completed",
        assistant_message="```study-ui\n" + json.dumps(card) + "\n```",
    )


def test_capability_survives_history_restore_and_bounded_patch():
    saved = turn(["three"])
    assert find_interactive_versions(
        [dict(role="assistant", content=saved.assistant_message)]
    )[0].capabilities == ("three",)
    outcome = locate_restore_source([saved], RestoreRequest("scene", 1))
    assert outcome.capabilities == ("three",)
    assert "capabilities: ['three']" in restore_context_block(outcome)
    patched = prepare_patch(
        [saved],
        RestoreRequest("scene", 1),
        source_hash("<p>old</p>"),
        [TextEdit("old", "new")],
    )
    assert patched.capabilities == ("three",)
    assert patched.html == "<p>new</p>"


def test_unknown_capability_is_not_a_saved_component():
    for capabilities in (["cdn"], ["three", "three"], "three", None):
        saved = turn(capabilities)
        assert (
            find_interactive_versions(
                [dict(role="assistant", content=saved.assistant_message)]
            )
            == []
        )


def test_equal_html_with_different_capabilities_is_a_conflict():
    assert (
        locate_restore_source(
            [turn([]), turn(["three"])], RestoreRequest("scene", 1)
        ).status
        == "conflict"
    )
