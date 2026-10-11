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

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any, Iterable, Mapping

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
    content_hash: str = ""
    #: Stable id for this run's content version (`S1`, `S2`, ...). The model cites this, so a
    #: citation always resolves to the exact body the run registered, never to a URL string.
    source_id: str = ""
    #: What was requested, so a redirect/rebrand is distinguishable from the final document.
    requested_url: str = ""

    def to_view(self, *, verified: bool = False) -> dict[str, Any]:
        return {"source_id": self.source_id, "url": self.url,
                "requested_url": self.requested_url, "final_url": self.final_url,
                "host": self.host, "chars": self.chars, "digest": self.digest,
                "content_hash": self.content_hash[:16], "goals": self.goals,
                # A body read after the last verification cycle stays visibly pending, so a
                # finding it contains is never confused with a checked one.
                "pending_verification": not verified}


@dataclass
class ResearchNotebook:
    """The run's own record. Populated on read; never written from model output."""

    bodies: dict[str, CachedBody] = field(default_factory=dict)
    #: `S1`, `S2`, ... -> the body registered under that id, in read order.
    by_source: dict[str, CachedBody] = field(default_factory=dict)
    #: Bodies already consumed by a verification cycle (their content version is bound).
    verified: set[str] = field(default_factory=set)
    _next_source: int = 1

    def mark_verified(self, source_ids: Iterable[str]) -> None:
        for source_id in source_ids:
            if source_id:
                self.verified.add(source_id)

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
        full_hash = sha256(body.encode("utf-8", "ignore")).hexdigest()
        source_id = f"S{self._next_source}"
        self._next_source += 1
        cached = CachedBody(url=url, final_url=final_url or url, host=host,
                            digest=full_hash[:12], chars=len(body), text=body,
                            goals=sorted(set(goals or [])), content_hash=full_hash,
                            source_id=source_id, requested_url=url)
        self.bodies[url] = cached
        self.by_source[source_id] = cached
        while len(self.bodies) > MAX_BODIES:                # bound the cache, oldest first
            dropped_url = next(iter(self.bodies))
            evicted = self.bodies.pop(dropped_url)
            self.by_source.pop(evicted.source_id, None)
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
                   claims: list[Any] | None = None,
                   verdicts: list[Any] | None = None,
                   followups: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """A bounded, per-round picture: goals, best evidence, gaps, what failed, what next."""
        goal_rows = []
        for label, terms in goals.items():
            state = goal_state.get(label) or {}
            records = list(goal_evidence.get(label) or [])
            shown = []
            for record in records[:MAX_EVIDENCE_PER_GOAL]:
                url = record.get("url", "")
                cached = self.bodies.get(url)
                excerpt = record.get("excerpt") or self.excerpt(url, tuple(terms))
                shown.append({
                    "source": url,
                    "host": record.get("host", ""),
                    # The adopted record keeps its own digest, so evicting the full text from
                    # the cache cannot break the audit trail.
                    "digest": record.get("digest") or (cached.digest if cached else ""),
                    "excerpt": str(excerpt)[:MAX_EXCERPT_CHARS],
                    "basis": "verbatim excerpt from this run",
                    "status": record.get("status", "explored"),
                    "full_text_cached": cached is not None,
                    "verification": RULE_VERIFICATION if record.get("status") == "supported"
                    else "candidate only - no verification yet",
                })
            goal_rows.append({
                "goal": label,
                "status": state.get("status", "missing"),
                "evidence": shown,
                "gap": "no candidate read yet" if state.get("status") == "missing"
                else ("has candidates, needs verification" if state.get("status") == "explored"
                      else "rule-verified excerpt on record"),
            })
        view = {
            "goals": goal_rows,
            "read_sources": [body.to_view(verified=body.source_id in self.verified)
                             for body in list(self.bodies.values())[-MAX_READ_SOURCES:]],
            "invalid_actions": refused[-MAX_INVALID_ACTIONS:],
            "next_action": next_action or {},
            # Candidate claims and their verification verdicts: the model reads these, it
            # can never write them back into the run's state.
            "claims": [asdict(item) if hasattr(item, "__dataclass_fields__") else item
                       for item in (claims or [])][:6],
            "claim_verdicts": [asdict(item) if hasattr(item, "__dataclass_fields__") else item
                               for item in (verdicts or [])][:6],
            "followups": (followups or [])[:2],
            "rules": ("excerpts are verbatim from this run; a rule-verified row is NOT a "
                      "semantic proof and grants no publication authority; an internal "
                      "'supported' verdict comes only from the claim verifier"),
        }
        return view


def view_size(view: dict[str, Any]) -> int:
    """Rough size in characters, used to keep the injected view bounded."""
    import json

    return len(json.dumps(view, ensure_ascii=False))
