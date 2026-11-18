"""Safety contract for the browser judgement used by the live Crawl4AI reader."""

import pytest

from src.web.research.browser_honesty import (
    HONESTY_DETAIL,
    HONESTY_DOWNGRADES,
    HONESTY_PREFIX_CHARS,
    honesty_outcome,
    rendered_content_judgement,
)
from src.web.research.failure_taxonomy import classify


@pytest.mark.parametrize("state", sorted(HONESTY_DOWNGRADES))
def test_browser_wall_downgrades_use_the_frozen_failure_taxonomy(state: str) -> None:
    projected = honesty_outcome(state, backend="crawl4ai")
    assert projected.state == state
    assert projected == classify(
        backend="crawl4ai", raw_state="", detail=HONESTY_DETAIL[state], adequacy_shape=""
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Please log in to continue reading", "login_required"),
        ("Please complete the CAPTCHA to continue", "anti_bot"),
        ("You need to enable JavaScript to run this app", "shell_page"),
        ("A technical article about browser support.", ""),
        ("", ""),
    ],
)
def test_browser_judgement_distinguishes_walls_from_content(text: str, expected: str) -> None:
    assert rendered_content_judgement(text) == expected


def test_late_login_mention_is_not_a_browser_wall() -> None:
    article = "ordinary prose about software. " * 400
    assert len(article) > HONESTY_PREFIX_CHARS
    assert rendered_content_judgement(article + " please log in") == ""
    assert rendered_content_judgement("please log in " + article) == "login_required"
