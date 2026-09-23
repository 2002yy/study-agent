"""§116 P2-A3-2c: the provider-neutral browser honesty layer.

A rendered login wall, challenge interstitial or JS shell is **not content**.
That judgement is a property of the frozen A0 marker table, not of any provider,
so it lives here rather than inside one vendor's executor - otherwise the next
browser backend would either duplicate it or, worse, inherit it by importing a
*disqualified* provider's module.

No new marker or capability word is introduced: the detection delegates to
``failure_taxonomy.state_for_text``, and the detected state is mapped back onto
a frozen marker literal so the outcome is still produced by ``classify``.
"""

from __future__ import annotations

from typing import Mapping

from src.web.research.failure_taxonomy import classify, state_for_text

#: How much of the rendered text the honesty check may look at. A wall or
#: interstitial announces itself at the top; scanning the whole document would
#: let an unrelated mention deep in an article masquerade as a challenge.
HONESTY_PREFIX_CHARS = 4000

#: The only canonical states a rendered page may be downgraded to.
HONESTY_DOWNGRADES: frozenset[str] = frozenset(
    {"login_required", "anti_bot", "shell_page"}
)

#: Bridge from a detected state back to a frozen marker literal, so the outcome
#: is produced by ``failure_taxonomy.classify`` rather than hand-built.
#: ``tests/test_browser_honesty.py`` asserts each entry round-trips.
HONESTY_DETAIL: Mapping[str, str] = {
    "login_required": "login required",
    "anti_bot": "captcha",
    "shell_page": "enable javascript",
}


def rendered_content_judgement(text: str) -> str:
    """Canonical state for a rendered page, or ``""`` when it looks like content.

    Uses the frozen marker table (``failure_taxonomy.state_for_text``); this
    function invents no marker of its own.
    """

    prefix = str(text or "")[:HONESTY_PREFIX_CHARS].lower()
    if not prefix:
        return ""
    state = state_for_text(prefix)
    return state if state in HONESTY_DOWNGRADES else ""


def honesty_outcome(judgement: str, backend: str):
    """The canonical outcome for a downgraded page (never hand-built)."""

    return classify(
        backend=str(backend),
        raw_state="",
        detail=HONESTY_DETAIL[judgement],
        adequacy_shape="",
    )


__all__ = [
    "HONESTY_DETAIL",
    "HONESTY_DOWNGRADES",
    "HONESTY_PREFIX_CHARS",
    "honesty_outcome",
    "rendered_content_judgement",
]
