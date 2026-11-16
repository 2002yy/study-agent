"""Choose a search channel from the query's shape.

A multi-constraint CJK question is the case where the two channels can diverge:
a free probe saw SearXNG return homepages for 4/4 topics while the browser's
Bing returned on-topic pages, and a later controlled run saw both return the
same on-topic list. The lane is therefore a coverage backup, not a claim that
one channel is always better; English documentation queries stay on the cheap
fast path.

The decision is deliberately two-valued: a channel that is a known loser is not
used alone, and an uncertain query runs both channels concurrently. Whether the
fast channel's results are *sufficient* is a separate, evidence-level question
owned by the caller; this module never decides that.
"""

from __future__ import annotations

import re

_CJK = re.compile(r"[\u4e00-\u9fff]")
_TERM_SPLIT = re.compile(r"[\s,，、;；:：/]+")
_SITE_CONSTRAINTS = ("site:", "domain:")

FAST = "fast"
DUAL = "dual"


def count_cjk(text: str) -> int:
    return len(_CJK.findall(text))


def route_search(query: str) -> str:
    """Return ``DUAL`` when both channels should run, else ``FAST``.

    A query that already carries a site/domain constraint belongs to the
    existing domain-first routing; a general engine page would ignore the
    constraint and spend a browser slot for nothing.
    """

    text = " ".join(str(query or "").split())
    if not text:
        return FAST
    lowered = text.casefold()
    if any(marker in lowered for marker in _SITE_CONSTRAINTS):
        return FAST
    if count_cjk(text) < 6:
        return FAST
    terms = [part for part in _TERM_SPLIT.split(text) if len(part) >= 2]
    if len(terms) >= 2 or count_cjk(text) >= 10:
        return DUAL
    return FAST
