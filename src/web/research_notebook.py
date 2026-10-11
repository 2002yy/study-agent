"""Run-local research notebook: what this run read, what it proves, and what is missing.

The notebook is a VIEW over authoritative run state (goals, per-goal evidence, calls) plus
an in-run cache of the text the run actually read. It exists so that a 20-round run keeps a
stable picture of its own progress instead of depending on the last six observations.

Rules kept deliberately:
* the model only READS the notebook; it is rebuilt from authoritative state every round, so
  the model can never edit an excerpt, a source identity or a verification status;
* building it costs no model call - it is pure Python over the run's own state;
* facts and judgements stay separate: an excerpt is verbatim; the deterministic
  terms+relation check is labelled as a RULE, not as semantic proof.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Mapping

MAX_BODIES = 8                 # cached bodies per run
MAX_BODY_CHARS = 6_000         # per cached body (what the reader handed the agent)
MAX_EVIDENCE_PER_GOAL = 2      # excerpt rows shown per goal
MAX_EXCERPT_CHARS = 180
MAX_READ_SOURCES = 6
MAX_INVALID_ACTIONS = 4
RULE_VERIFICATION = "rule: same-window terms+relation (deterministic, not semantic proof)"


@dataclass
class CachedBody:
    """One body this run actually read, kept so excerpts can be traced without re-fetching."""

    url: str
    final_url: str
    host: str
    digest: str
    chars: int
    text: str
    goals: list[str] = field(default_factory=list)

    def to_view(self) -> dict[str, Any]:
        full_hash = sha256(self.text.encode("utf-8")).hexdigest()
        source_id = sha256((self.final_url + "\n" + full_hash).encode("utf-8")).hexdigest()[:20]
        return {"url": self.url, "final_url": self.final_url,
                "host": self.host, "chars": self.chars, "digest": self.digest,
                "content_hash": full_hash, "source_id": source_id,
                "goals": self.goals}


@dataclass
class ResearchNotebook:
    """The run's own record. Populated on read; never written from model output."""

    bodies: dict[str, CachedBody] = field(default_factory=dict)

    def record(self, url: str, final_url: str, text: str,
               goals: list[str] | None = None) -> CachedBody | None:
        """Cache a body the run just read. Duplicates keep the first (authoritative) copy."""
        body = (text or "")[:MAX_BODY_CHARS]
        if not url or not body:
            return None
        existing = self.bodies.get(url)
        if existing is not None:
            if goals:
                existing.goals = sorted(set(existing.goals) | set(goals))
            return existing
        host = (final_url or url).split("/")[2] if "//" in (final_url or url) else ""
        cached = CachedBody(url=url, final_url=final_url or url, host=host,
                            digest=sha256(body.encode("utf-8", "ignore")).hexdigest()[:12],
                            chars=len(body), text=body, goals=sorted(set(goals or [])))
        self.bodies[url] = cached
        while len(self.bodies) > MAX_BODIES:                # bound the cache, oldest first
            self.bodies.pop(next(iter(self.bodies)))
        return cached

    def excerpt(self, url: str, terms: tuple[str, ...] | list[str],
                window: int = 90) -> str:
        """A verbatim excerpt around the goal terms, from cache and without any network."""
        cached = self.bodies.get(url)
        if cached is None:
            return ""
        lowered = cached.text.lower()
        for term in terms:
            position = lowered.find(str(term).lower())
            if position >= 0:
                start, end = max(0, position - window), position + window
                return cached.text[start:end].replace("\n", " ")
        return cached.text[:MAX_EXCERPT_CHARS].replace("\n", " ")

    def build_view(self, *, goals: Mapping[str, Any], goal_state: Mapping[str, Any],
                   goal_evidence: Mapping[str, list[dict[str, Any]]],
                   refused: list[dict[str, str]],
                   next_action: dict[str, str] | None,
                   assertions: list[dict[str, Any]] | None = None,
                   gaps: list[dict[str, str]] | None = None,
                   extraction_used: bool = False,
                   pending_sources: list[str] | None = None) -> dict[str, Any]:
        """A bounded, per-round picture: goals, best evidence, gaps, what failed, what next."""
        goal_rows = []
        for label, terms in goals.items():
            state = goal_state.get(label) or {}
            records = list(goal_evidence.get(label) or [])
            shown = []
            prioritized: list[dict[str, Any]] = []
            # Surface late unverified reads before old records, while retaining one
            # independently verified quote when possible.
            for record in (
                [row for row in reversed(records)
                 if row.get("verification_state") == "pending_new_read"]
                + [row for row in records
                   if row.get("verified_by") == "independent_semantic"]
                + records
            ):
                if record not in prioritized:
                    prioritized.append(record)
                if len(prioritized) >= MAX_EVIDENCE_PER_GOAL:
                    break
            for record in prioritized:
                url = record.get("url", "")
                cached = self.bodies.get(url) or next(
                    (body for body in self.bodies.values() if body.final_url == url), None)
                excerpt = record.get("excerpt") or self.excerpt(url, tuple(terms))
                shown.append({
                    "source": url,
                    "host": record.get("host", ""),
                    # The adopted record keeps its own digest, so evicting the full text from
                    # the cache cannot break the audit trail.
                    "digest": record.get("digest") or (cached.digest if cached else ""),
                    "source_id": record.get("source_id", ""),
                    "content_hash": record.get("content_hash", ""),
                    "span_start": record.get("span_start"),
                    "span_end": record.get("span_end"),
                    "excerpt": str(excerpt)[:MAX_EXCERPT_CHARS],
                    "basis": "verbatim excerpt from this run",
                    "status": record.get("status", "explored"),
                    "full_text_cached": cached is not None,
                    "verification": (
                        "independent semantic verdict on same-read bound span "
                        "(not publication authority)"
                        if (record.get("status") == "supported"
                            and record.get("verified_by") == "independent_semantic")
                        else RULE_VERIFICATION + "; not semantic proof"
                        if record.get("status") == "supported"
                        else "candidate only - not semantic proof"
                        if record.get("verified_by") != "independent_semantic"
                        else "independent semantic verdict: " + str(record.get("status"))
                    ),
                })
            goal_rows.append({
                "goal": label,
                "status": state.get("status", "missing"),
                "evidence": shown,
                "gap": "newly read source pending independent verification"
                if any(row.get("verification_state") == "pending_new_read"
                       for row in records)
                else "no candidate read yet" if state.get("status") == "missing"
                else ("has candidates, needs verification" if state.get("status") == "explored"
                      else "contradictory evidence; research further"
                      if state.get("status") == "conflict"
                      else "independently checked excerpt on record"),
            })
        view = {
            "goals": goal_rows,
            "read_sources": [body.to_view() for body in
                             list(self.bodies.values())[-MAX_READ_SOURCES:]],
            "invalid_actions": refused[-MAX_INVALID_ACTIONS:],
            "next_action": next_action or {},
            "rules": ("excerpts are verbatim from this run; keyword rules are "
                      "candidate filters only. Only an independently checked same-read "
                      "span may count as supported; no publication authority."),
        }
        if assertions:
            view["assertions"] = [
                {"goal": row.get("goal"), "claim": str(row.get("claim", ""))[:220],
                 "status": row.get("status", "pending"),
                 "source_id": row.get("source_id", "")}
                for row in assertions[:6]
            ]
        if gaps:
            view["gaps"] = gaps[:3]
        if extraction_used:
            view["semantic_batch_used"] = True
        if pending_sources:
            view["pending_verification_sources"] = pending_sources[-3:]
        return view


def view_size(view: dict[str, Any]) -> int:
    """Rough size in characters, used to keep the injected view bounded."""
    import json

    return len(json.dumps(view, ensure_ascii=False))
