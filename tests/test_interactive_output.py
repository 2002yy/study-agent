from dataclasses import replace

import pytest

from src.interactive_history import find_interactive_versions
from src.interactive_output import normalize_interactive_output
from src.interactive_restore import RestoreOutcome, RestoreRequest

SOURCE = RestoreOutcome(
    RestoreRequest("scene", 1), "restored", "saved", "turn", 3, "", ("three",)
)
HTML = '<!doctype html><html><head><title>x</title></head><body><script>const s="</html>";</script><p>x</p></body></html>'


@pytest.mark.parametrize("reply", [HTML, "```html\n" + HTML + "\n```"])
def test_complete_html_uses_saved_identity_and_preserves_source(reply):
    result = normalize_interactive_output(reply, SOURCE, "stop")
    versions = find_interactive_versions([{"role": "assistant", "content": result}])
    assert len(versions) == 1
    assert (versions[0].id, versions[0].revision, versions[0].capabilities) == (
        "scene",
        3,
        ("three",),
    )
    assert versions[0].html == HTML


@pytest.mark.parametrize(
    "reply",
    [
        "```js\nconst x=1;\n```",
        HTML[:-7],
        HTML + HTML,
        "```html\n" + HTML + "\n```\n```js\nx\n```",
        "Explanation\n" + HTML,
        HTML + "tail",
        "<html><head></head><body><script>x",
        "<html><head></head><body><p>x</body></html>",
        "```study-ui\n{}\n```",
        "<html><head></head><body/></html>",
    ],
)
def test_ambiguous_or_partial_output_is_unchanged(reply):
    assert normalize_interactive_output(reply, SOURCE, "stop") == reply


@pytest.mark.parametrize("reason", [None, "unknown", "length", "error"])
def test_nonterminal_generation_is_unchanged(reason):
    assert normalize_interactive_output(HTML, SOURCE, reason) == HTML


@pytest.mark.parametrize(
    "source",
    [
        None,
        replace(SOURCE, status="not_found"),
        replace(SOURCE, next_revision=1000),
        replace(SOURCE, html=None),
    ],
)
def test_missing_or_unusable_saved_source_is_unchanged(source):
    assert normalize_interactive_output(HTML, source, "stop") == HTML


def test_single_fence_with_prose_and_svg_preserves_prose():
    html = HTML.replace("<p>x</p>", '<svg><circle cx="2"/></svg>')
    reply = "说明\n```html\n" + html + "\n```\n结束"
    result = normalize_interactive_output(reply, SOURCE, "stop")
    assert result.startswith("说明\n```study-ui")
    assert result.endswith("\n结束")
    assert (
        find_interactive_versions([{"role": "assistant", "content": result}])[0].html
        == html
    )
