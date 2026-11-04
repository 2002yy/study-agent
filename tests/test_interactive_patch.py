import pytest

from src.interactive_patch import PatchConflict, TextEdit, prepare_patch, source_hash
from src.interactive_restore import RestoreRequest
from tools.interactive_patch_demo import saved_turn


def test_patch_is_source_bound_and_keeps_other_content_unchanged():
    html = "<p>old</p><button>Keep</button>"
    turns = [saved_turn(html, 1)]
    candidate = prepare_patch(
        turns,
        RestoreRequest("linear-demo", 1),
        source_hash(html),
        [TextEdit("old", "new")],
    )
    assert candidate.html == "<p>new</p><button>Keep</button>"
    assert candidate.revision == 2
    assert "old" in turns[0].assistant_message


@pytest.mark.parametrize(
    "edits",
    [
        [],
        [TextEdit("missing", "x")],
        [TextEdit("", "x")],
        [TextEdit("abc", "x"), TextEdit("bc", "y")],
    ],
)
def test_conflicts_never_partially_modify_saved_source(edits):
    html = "<p>abc</p>"
    turns = [saved_turn(html, 1)]
    before = turns[0].assistant_message
    with pytest.raises(PatchConflict):
        prepare_patch(turns, RestoreRequest("linear-demo", 1), source_hash(html), edits)
    assert turns[0].assistant_message == before


def test_ambiguous_anchor_and_stale_hash_are_rejected():
    html = "<p>abc abc</p>"
    turns = [saved_turn(html, 1)]
    for digest, anchor in [(source_hash(html), "abc"), (source_hash("old"), "<p>")]:
        with pytest.raises(PatchConflict):
            prepare_patch(
                turns, RestoreRequest("linear-demo", 1), digest, [TextEdit(anchor, "x")]
            )


def test_new_revision_uses_full_saved_history_and_wrong_identity_cannot_patch():
    html = "<p>old</p>"
    turns = [saved_turn(html, 1), saved_turn("<p>later</p>", 4)]
    result = prepare_patch(
        turns,
        RestoreRequest("linear-demo", 1),
        source_hash(html),
        [TextEdit("old", "new")],
    )
    assert result.revision == 5
    with pytest.raises(PatchConflict):
        prepare_patch(
            turns,
            RestoreRequest("other", 1),
            source_hash(html),
            [TextEdit("old", "new")],
        )


def test_out_of_bounds_candidate_is_rejected():
    html = "<p>old</p>"
    with pytest.raises(PatchConflict):
        prepare_patch(
            [saved_turn(html, 1)],
            RestoreRequest("linear-demo", 1),
            source_hash(html),
            [TextEdit("old", "x" * 60001)],
        )


def test_whole_document_replacement_is_not_a_local_patch():
    html = "<p>old</p>"
    with pytest.raises(PatchConflict, match="whole-document"):
        prepare_patch(
            [saved_turn(html, 1)],
            RestoreRequest("linear-demo", 1),
            source_hash(html),
            [TextEdit(html, "<p>new</p>")],
        )


def test_overlapping_occurrences_are_ambiguous_anchors():
    html = "<p>aaa</p>"
    turns = [saved_turn(html, 1)]
    before = turns[0].assistant_message
    with pytest.raises(PatchConflict, match="exactly once"):
        prepare_patch(
            turns,
            RestoreRequest("linear-demo", 1),
            source_hash(html),
            [TextEdit("aa", "b")],
        )
    assert turns[0].assistant_message == before
