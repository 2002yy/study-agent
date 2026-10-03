"""§144.13 boundary 1: declarative visual-metadata projection."""

from __future__ import annotations

from src.web.research.visual_metadata import (
    MAX_VISUAL_METADATA_ENTRIES,
    VISUAL_METADATA_KEY,
    project_visual_metadata,
)

_VALID = {
    "image_id": "fig4",
    "kind": "chart",
    "source": "report.pdf",
    "page": 4,
    "region": "bbox:1",
    "alt": "platform support",
    "triggers": ["text_references_figure"],
    "carries_required_evidence": True,
}


def test_projection_is_empty_without_the_declared_channel() -> None:
    assert project_visual_metadata({}) == ()
    assert project_visual_metadata(None) == ()
    assert project_visual_metadata({"visual_metadata": "not-a-list"}) == ()


def test_projection_normalizes_a_valid_entry() -> None:
    images = project_visual_metadata({VISUAL_METADATA_KEY: [_VALID]})

    assert len(images) == 1
    image = images[0]
    assert image.image_id == "fig4"
    assert image.kind == "chart"
    assert image.page == 4
    assert image.provenance == "report.pdf#page=4#region=bbox:1"
    assert image.carries_required_evidence is True
    assert image.local_path == ""


def test_projection_drops_unknown_kinds_sources_and_triggers() -> None:
    entries = [
        {**_VALID, "kind": "hologram"},
        {**_VALID, "source": ""},
        {**_VALID, "triggers": []},
        {**_VALID, "triggers": ["made_up_trigger"]},
        {**_VALID, "image_id": ""},
        "not-a-mapping",
    ]

    assert project_visual_metadata({VISUAL_METADATA_KEY: entries}) == ()


def test_projection_never_invents_a_trigger_from_other_fields() -> None:
    entry = {k: v for k, v in _VALID.items() if k != "triggers"}
    entry["alt"] = "looks like a chart"

    assert project_visual_metadata({VISUAL_METADATA_KEY: [entry]}) == ()


def test_projection_is_bounded() -> None:
    entries = [{**_VALID, "image_id": f"i{n}"} for n in range(MAX_VISUAL_METADATA_ENTRIES + 5)]

    images = project_visual_metadata({VISUAL_METADATA_KEY: entries})

    assert len(images) == MAX_VISUAL_METADATA_ENTRIES


def test_projection_coerces_a_bad_page_to_absent() -> None:
    images = project_visual_metadata({VISUAL_METADATA_KEY: [{**_VALID, "page": "4"}]})

    assert images[0].page is None
    assert images[0].provenance == "report.pdf#region=bbox:1"
