from __future__ import annotations

from types import SimpleNamespace

from src.api.routes.chat_routes import pedagogy_summary_from_plan


def _plan(**overrides):
    base = {
        "mode": "socratic",
        "phase": "scaffold",
        "move": "give_hint",
        "disclosure_level": 2,
        "knowledge_kind": "derivable",
        "learner_claim": "",
        "unresolved_gap": "",
        "target_understanding": "",
        "library_needed": False,
        "evidence_ids": (),
        "constraints": (),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_pedagogy_summary_picks_compact_fields():
    summary = pedagogy_summary_from_plan(_plan())
    assert summary == {
        "mode": "socratic",
        "phase": "scaffold",
        "move": "give_hint",
        "disclosure_level": 2,
    }


def test_pedagogy_summary_handles_missing_attributes():
    summary = pedagogy_summary_from_plan(SimpleNamespace())
    assert summary == {"mode": "", "phase": "", "move": "", "disclosure_level": 0}
