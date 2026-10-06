"""Standard-4: project a durable Standard journal into binding inputs.

This is the deterministic bridge between Standard-2's persisted research and Standard-3's
mechanical binding. It proposes; it does not decide.

Two rules keep it honest.

**Trusted sources come from the durable journal, re-hashed.** A source is admitted only when a
readable read observation names a completed journal entry whose body re-hashes to the digest
the observation recorded. A caller-supplied digest is never trusted.

**A claim needs the target and the relation in the same evidence window.** A page that mentions
Python 3.14 in one place and a release date in another does not prove 3.14's release date, so
a window only yields a claim when the relation binder accepts it *and* the target identity
appears inside that same window. When the target is not unique, or the binder cannot derive a
value, no claim is produced and the field stays unresolved.

No model is involved. The normalized value is left empty so Standard-3 derives it from the
span.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

from src.web.research.standard_binding import Claim, TrustedSource, relation_binder_for

# Stable evidence boundaries: a claim never spans a sentence break.
_WINDOW_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
_MIN_WINDOW = 4
_MAX_WINDOW = 400


def journal_work_key(kind: str, target: str) -> str:
    """Mirror of the repository's entry key.

    Kept local so this module does not import the repository layer; a test pins the two
    derivations together.
    """

    return hashlib.sha256(json.dumps([kind, target]).encode()).hexdigest()


def _body_of(entry: dict) -> str:
    result = entry.get("result") or {}
    body = result.get("content") or result.get("readme") or ""
    return body if isinstance(body, str) else ""


def project_trusted_sources(ledger: dict) -> list[TrustedSource]:
    """Readable read observations whose journal body re-hashes to the recorded digest."""

    observations = ((ledger or {}).get("research") or {}).get("observations") or []
    entries = (ledger or {}).get("entries") or {}
    sources: list[TrustedSource] = []
    for observation in observations:
        if observation.get("kind") != "read" or not observation.get("readable"):
            continue
        entry = entries.get(journal_work_key("read", str(observation.get("target"))))
        if not isinstance(entry, dict) or entry.get("state") != "completed":
            continue
        body = _body_of(entry)
        if not body.strip():
            continue
        digest = hashlib.sha256(body.encode()).hexdigest()
        if digest != str(observation.get("content_sha256") or ""):
            # The recorded digest does not describe this body: refuse the source.
            continue
        sources.append(
            TrustedSource(
                url=str(observation.get("target") or ""),
                content_sha256=digest,
                body=body,
                # No server-owned role authority exists yet; never guess primary/secondary.
                source_role="",
            )
        )
    return sources


def evidence_windows(body: str) -> list[tuple[str, int, int]]:
    """Bounded exact windows with their original offsets.

    Every window is a slice of the body, so ``body[start:end] == text`` holds and Standard-3's
    offset cross-check can only agree.
    """

    text = str(body or "")
    boundaries = [0]
    # A period only ends a sentence before whitespace or end of text, so version numbers such
    # as "3.14.0" are never split across windows.
    for match in re.finditer(r"[!?;]|\n|\.(?=\s|$)", text):
        boundaries.append(match.end())
    boundaries.append(len(text))

    windows: list[tuple[str, int, int]] = []
    for start, stop in zip(boundaries, boundaries[1:]):
        segment = text[start:stop]
        stripped = segment.strip()
        if not (_MIN_WINDOW <= len(stripped) <= _MAX_WINDOW):
            continue
        offset = start + (len(segment) - len(segment.lstrip()))
        windows.append((stripped, offset, offset + len(stripped)))
    return windows


def target_identity_pattern(target: str) -> str | None:
    """A pattern that matches the target's tokens in order, or None when there is no target."""

    tokens = [tok for tok in re.split(r"\s+", str(target or "").strip()) if tok]
    if not tokens:
        return None
    return r"\b" + r"\s*".join(re.escape(tok) for tok in tokens) + r"\b"


def project_mechanical_claims(
    fields: Iterable[str],
    trusted: Iterable[TrustedSource],
    *,
    target: str,
) -> list[Claim]:
    """Deterministic candidate claims: relation and target identity in the same window."""

    pattern = target_identity_pattern(target)
    if pattern is None:
        # No unique target: refuse to propose anything rather than bind a neighbouring fact.
        return []
    claims: list[Claim] = []
    for field in fields:
        binder = relation_binder_for(field)
        if binder is None:
            continue
        for source in trusted:
            for text, start, _end in evidence_windows(source.body):
                if binder(text) is None:
                    continue
                if not re.search(pattern, text, re.I):
                    continue
                claims.append(
                    Claim(
                        field=field,
                        source_url=source.url,
                        source_sha256=source.content_sha256,
                        span_text=text,
                        span_start=start,
                    )
                )
    return claims


def project_binding_inputs(
    ledger: dict,
    fields: Iterable[str],
    *,
    target: str,
) -> dict[str, Any]:
    """The whole projection, for the continuation service."""

    trusted = project_trusted_sources(ledger)
    claims = project_mechanical_claims(fields, trusted, target=target)
    return {"trusted_sources": trusted, "claims": claims}
