"""Per-read budgets: pages stay short, docs and PDFs get more room."""

from __future__ import annotations

from src.web.read_budget import read_budget_seconds


def test_a_page_keeps_the_short_budget():
    assert read_budget_seconds(
        "https://example.com/story", remaining=60, page_seconds=8
    ) == 8


def test_a_documentation_page_gets_the_large_document_budget():
    assert read_budget_seconds(
        "https://example.com/news/story", remaining=60
    ) == 15
    assert read_budget_seconds(
        "https://docs.example.org/guide/install", remaining=60
    ) == 30
    assert read_budget_seconds(
        "https://example.org/documentation/install", remaining=60
    ) == 30


def test_a_pdf_gets_more_than_a_page_but_not_the_whole_window():
    budget = read_budget_seconds(
        "https://example.com/paper.pdf", remaining=120, page_seconds=8
    )
    assert budget == 60


def test_audio_gets_media_room_capped_by_the_remaining_window():
    assert read_budget_seconds(
        "https://cdn.example.com/ep.mp3", remaining=45
    ) == 45
    assert read_budget_seconds(
        "https://cdn.example.com/ep.mp3", remaining=240
    ) == 240
    assert read_budget_seconds(
        "https://cdn.example.com/ep.mp3", remaining=600
    ) == 330


def test_an_exhausted_window_gets_no_budget():
    assert read_budget_seconds("https://example.com/a.mp3", remaining=0) == 0
    assert read_budget_seconds("https://example.com/a.mp3", remaining=-3) == 0
