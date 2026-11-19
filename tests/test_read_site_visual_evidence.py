"""§144.15 read-site single insertion for visual evidence (default-inert).

Operator-style end-to-end runs through the real read site with deterministic
fakes: no network and no model call, but the real `execute()` path. The
invariants under test are the ones that make the insertion safe to ship:

* vision disabled (the default) is byte-equivalent to the production baseline;
* declared metadata with vision disabled has zero side effects;
* enabled vision produces provenance-anchored units plus an audit record;
* a visual failure never turns a successful text read into a failure.
"""

from __future__ import annotations

from src.application import active_research_runtime as runtime
from src.application.research_vision_adapter import build_research_vision_adapter
from src.news.url_normalizer import canonicalize_url
from src.web.research.visual_read_budget import MAX_VISION_CALLS_ENV
from tests.research_read_site_scenarios import ART, run_read_site_scenario

_PNG = b"\x89PNG\r\n\x1a\n" + b"v" * 40
_METADATA = {
    "image_id": "fig4",
    "kind": "chart",
    "source": "https://docs.example/report.pdf",
    "page": 4,
    "region": "bbox:10,10,200,120",
    "triggers": ["text_references_figure"],
    "carries_required_evidence": True,
}


def _execute(monkeypatch, tmp_path, *, extra=None, vision_calls=None, tag="visual"):
    if vision_calls is None:
        monkeypatch.delenv(MAX_VISION_CALLS_ENV, raising=False)
    else:
        monkeypatch.setenv(MAX_VISION_CALLS_ENV, str(vision_calls))

    context = ART._active_context()
    context.update(extra or {})
    return run_read_site_scenario(
        tmp_path=tmp_path,
        sqlite_name=f"{tag}.sqlite",
        run_id=f"run_{tag}",
        context=context,
    )


def _shape(completed):
    rows = ART._chain_rows(completed)
    return (
        [[step["backend"] for step in row["steps"]] for row in rows],
        [
            str(item.get("read", {}).get("status"))
            for item in (completed.selected_sources or [])
        ],
        [
            str(item.get("read", {}).get("content", ""))[:64]
            for item in (completed.selected_sources or [])
        ],
    )


def _metrics(completed):
    return completed.research_context.get(runtime.ACTIVE_RESEARCH_METRICS_KEY) or {}


def _sources(completed):
    return [dict(item) for item in (completed.selected_sources or [])]


def _observed_urls(completed):
    urls = []
    for item in _sources(completed):
        url = str(
            (item.get("item") or {}).get("url") or item.get("read", {}).get("url") or ""
        )
        if url:
            urls.append(url)
    return urls


def _declaration_for(completed):
    return {
        canonicalize_url(url): {
            "visual_metadata": [_METADATA],
            "required_units": ["fig4"],
        }
        for url in _observed_urls(completed)
    }


def test_baseline_read_site_has_no_visual_side_effects(monkeypatch, tmp_path) -> None:
    completed = _execute(monkeypatch, tmp_path, tag="baseline")

    assert "visual_reads" not in _metrics(completed)
    assert all("visual_units" not in item for item in _sources(completed))
    assert "visual_external_calls" not in completed.research_context


def test_declared_metadata_with_vision_disabled_is_inert(monkeypatch, tmp_path) -> None:
    baseline = _execute(monkeypatch, tmp_path, tag="base2")
    declaration = _declaration_for(baseline)
    assert declaration, "the baseline read must produce a source url"

    completed = _execute(
        monkeypatch,
        tmp_path,
        tag="inert",
        extra={runtime.VISUAL_METADATA_BY_URL_KEY: declaration},
    )

    assert "visual_reads" not in _metrics(completed)
    assert all("visual_units" not in item for item in _sources(completed))
    assert "visual_external_calls" not in completed.research_context
    assert _shape(completed) == _shape(baseline)


def test_enabled_vision_produces_units_and_audit(monkeypatch, tmp_path) -> None:
    baseline = _execute(monkeypatch, tmp_path, tag="base3")
    declaration = _declaration_for(baseline)
    fetches: list[str] = []

    def fetcher(url: str):
        fetches.append(url)
        return _PNG, "image/png"

    monkeypatch.setattr(runtime, "_VISUAL_IMAGE_FETCHER", fetcher)
    monkeypatch.setattr(
        runtime,
        "_VISUAL_VISION_ADAPTER",
        build_research_vision_adapter(enabled=True, describer=lambda path: "Figure 4: feature X unsupported."),
    )
    monkeypatch.setattr(runtime, "_VISUAL_IMAGE_DESTINATION", tmp_path / "images")
    completed = _execute(
        monkeypatch,
        tmp_path,
        tag="enabled",
        vision_calls=1,
        extra={runtime.VISUAL_METADATA_BY_URL_KEY: declaration},
    )

    records = [item for item in _sources(completed) if "visual_units" in item]
    assert records, "the declared image must produce visual units"
    unit = records[0]["visual_units"][0]
    assert unit["unit_id"] == "fig4"
    assert unit["source_type"] == "chart"
    assert unit["page"] == 4
    assert unit["provenance"].startswith("https://docs.example/report.pdf#page=4")

    visual_reads = _metrics(completed)["visual_reads"]
    assert visual_reads and visual_reads[0]["vision_calls"] == 1
    assert set(fetches) == {"https://docs.example/report.pdf"}

    audit = completed.research_context["visual_external_calls"]
    assert audit and audit[0]["purpose"] == "image_description"
    assert audit[0]["status"] == "normalized"

    # The read path itself is untouched: same chain backends, same statuses,
    # same text content as the baseline.
    assert _shape(completed) == _shape(baseline)


def test_visual_failure_keeps_the_text_read_successful(monkeypatch, tmp_path) -> None:
    baseline = _execute(monkeypatch, tmp_path, tag="base4")
    declaration = _declaration_for(baseline)

    def exploding_fetcher(url: str):
        raise RuntimeError("network down")

    monkeypatch.setattr(runtime, "_VISUAL_IMAGE_FETCHER", exploding_fetcher)
    monkeypatch.setattr(runtime, "_VISUAL_IMAGE_DESTINATION", tmp_path / "images")
    completed = _execute(
        monkeypatch,
        tmp_path,
        tag="failing",
        vision_calls=1,
        extra={runtime.VISUAL_METADATA_BY_URL_KEY: declaration},
    )

    # The text read is still a success and its shape is unchanged.
    assert _shape(completed) == _shape(baseline)
    assert all(
        str(item.get("read", {}).get("status")) == "read" for item in _sources(completed)
    )
    assert all("visual_units" not in item for item in _sources(completed))

    visual_reads = _metrics(completed)["visual_reads"]
    assert visual_reads[0]["vision_calls"] == 0
    assert visual_reads[0]["outcomes"][0]["status"] == "unavailable"
    assert visual_reads[0]["outcomes"][0]["reason"] == "image_fetch_failed"


def test_visual_side_never_touches_the_read_budget(monkeypatch, tmp_path) -> None:
    # reads_used is derived from successful reads only; enabling vision must not
    # change how many reads the run records.
    baseline = _execute(monkeypatch, tmp_path, tag="base5")
    declaration = _declaration_for(baseline)

    monkeypatch.setattr(
        runtime, "_VISUAL_IMAGE_FETCHER", lambda url: (_PNG, "image/png")
    )
    monkeypatch.setattr(runtime, "_VISUAL_IMAGE_DESTINATION", tmp_path / "images")
    completed = _execute(
        monkeypatch,
        tmp_path,
        tag="budget",
        vision_calls=1,
        extra={runtime.VISUAL_METADATA_BY_URL_KEY: declaration},
    )

    baseline_reads = [
        item for item in _sources(baseline) if item.get("read", {}).get("ok")
    ]
    vision_reads = [
        item for item in _sources(completed) if item.get("read", {}).get("ok")
    ]
    assert len(vision_reads) == len(baseline_reads)
