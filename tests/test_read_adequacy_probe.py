"""§46 read adequacy probe: shape classification and summary contracts."""

from __future__ import annotations

from pathlib import Path

from tools.run_read_adequacy_probe import (
    classify_read,
    collect_sample_urls,
    probe_url,
    summarize,
)

HTML = (
    "<html><body><nav>menu</nav><article>"
    + ("Docker Hub pull rate limits apply. " * 60)
    + "</article></body></html>"
)


def test_ok_page_is_not_short() -> None:
    assert (
        classify_read(
            production_chars=1500,
            html_chars=9000,
            best_local_chars=1500,
            text="x" * 1500,
            final_url="https://docs.example/a",
            requested_url="https://docs.example/a",
        )
        == "ok"
    )


def test_short_js_shell_is_classified() -> None:
    assert (
        classify_read(
            production_chars=120,
            html_chars=4000,
            best_local_chars=120,
            text="Please enable JavaScript to continue.",
            final_url="https://docs.example/a",
            requested_url="https://docs.example/a",
        )
        == "js_shell"
    )


def test_anti_bot_marker_wins() -> None:
    assert (
        classify_read(
            production_chars=100,
            html_chars=4000,
            best_local_chars=100,
            text="Access denied: CAPTCHA required",
            final_url="https://docs.example/a",
            requested_url="https://docs.example/a",
        )
        == "anti_bot_or_error"
    )


def test_redirect_landing_is_detected() -> None:
    assert (
        classify_read(
            production_chars=300,
            html_chars=4000,
            best_local_chars=300,
            text="Welcome to the documentation home",
            final_url="https://docs.example/",
            requested_url="https://docs.example/a/b/",
        )
        == "redirect_landing"
    )


def test_extraction_loss_is_the_decisive_shape() -> None:
    # Same URL: production (trafilatura-precision) returns 520 chars, while a
    # local alternate extractor yields far more from the same HTML.
    assert (
        classify_read(
            production_chars=520,
            html_chars=120000,
            best_local_chars=4200,
            text="Article navigation and links only.",
            final_url="https://docs.example/a",
            requested_url="https://docs.example/a",
        )
        == "extraction_loss"
    )


def test_summary_answers_question_three() -> None:
    rows = [
        {"production_chars": 1500, "classification": "ok"},
        {"production_chars": 520, "classification": "extraction_loss"},
        {"production_chars": 200, "classification": "short_doc"},
    ]
    summary = summarize(rows)
    assert summary["short_pages"] == 2
    assert summary["short_ratio"] == 0.667
    assert summary["local_richer_available"] == 1
    assert summary["answer_question_3"].startswith("yes")

    no_gap = summarize([{"production_chars": 200, "classification": "short_doc"}])
    assert no_gap["answer_question_3"].startswith("no")


def test_probe_url_measures_all_extractors(tmp_path: Path) -> None:
    def production_reader(url: str) -> dict:
        del url
        return {"ok": True, "content": "short text", "method": "local_trafilatura"}

    def html_fetcher(url: str) -> tuple[str, str, str, str]:
        del url
        return HTML, "https://docs.example/a", "text/html", ""

    extractors = [
        ("trafilatura", lambda html: "short text"),
        ("readability", lambda html: "long text " * 200),
        ("fallback_parser", lambda html: "longer text " * 300),
    ]
    row = probe_url(
        "https://docs.example/a",
        production_reader=production_reader,
        html_fetcher=html_fetcher,
        extractors=extractors,
    )
    assert row["production_chars"] == len("short text")
    assert row["readability_chars"] > 1000
    assert row["fallback_parser_chars"] > row["readability_chars"]
    assert row["classification"] == "raw_other" or row["classification"] in {
        "extraction_loss",
        "short_doc",
    }
    assert row["best_local_chars"] >= row["fallback_parser_chars"]


def test_sample_collection_uses_artifacts_and_targets(tmp_path: Path) -> None:
    import json

    artifact = {
        "cases": [
            {
                "sources": [
                    {"url": "https://docs.example/a/b/"},
                    {"url": "https://example.com/"},
                ]
            }
        ]
    }
    path = tmp_path / "a.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    rows = collect_sample_urls([path], cap=10)
    urls = [url for url, _ in rows]
    assert "https://docs.example/a/b" in urls
    assert "https://example.com" not in urls
    assert any(source == "known_target" for _, source in rows)
