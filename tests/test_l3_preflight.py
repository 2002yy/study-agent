"""L3 preflight: positive and negative controls.

The point of the preflight is to refuse to start the expensive suite when a prerequisite
is already known to be unmet, so each negative control asserts the specific reason.
"""

from __future__ import annotations

import json

from tools import l3_preflight


def _git_stub(status: str = "", head: str = "a" * 40):
    def _fake(*args: str) -> str:
        if args[:1] == ("status",):
            return status
        if args[:2] == ("rev-parse", "HEAD"):
            return head + "\n"
        return ""

    return _fake


# --- positive -------------------------------------------------------------------


def test_clean_checkout_at_exact_head_passes(monkeypatch, tmp_path):
    monkeypatch.setattr(l3_preflight, "_git", _git_stub())
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    gates = tmp_path / "stage_gates.json"
    gates.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "levels": {},
                "impact_sets": {"x": []},
                "stage_gates": {},
                "force_l3_triggers": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(l3_preflight, "STAGE_GATES", gates)
    assert l3_preflight.run_checks() == []
    assert l3_preflight.main(["--quiet"]) == 0


# --- negative: dirty checkout ---------------------------------------------------


def test_dirty_tracked_checkout_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(l3_preflight, "_git", _git_stub(status=" M src/x.py\n"))
    monkeypatch.setattr(l3_preflight, "STAGE_GATES", tmp_path / "missing.json")
    failures = l3_preflight.run_checks()
    assert any(f.startswith("dirty_tracked_checkout") for f in failures)


def test_untracked_only_is_not_dirty(monkeypatch):
    # --untracked-files=no means the stub returning "" is the clean signal.
    monkeypatch.setattr(l3_preflight, "_git", _git_stub(status=""))
    assert l3_preflight.check_tracked_clean() == ""


# --- negative: head identity ----------------------------------------------------


def test_short_head_fails(monkeypatch):
    monkeypatch.setattr(l3_preflight, "_git", _git_stub(head="abc123"))
    reason, _sha = l3_preflight.check_exact_head()
    assert reason.startswith("head_is_not_exact_sha")


def test_github_sha_mismatch_fails(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    assert l3_preflight.check_github_sha("a" * 40).startswith("github_sha_mismatch")


def test_github_sha_absent_is_ok(monkeypatch):
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    assert l3_preflight.check_github_sha("a" * 40) == ""


# --- negative: gate configuration -----------------------------------------------


def test_invalid_stage_gates_fails(monkeypatch, tmp_path):
    gates = tmp_path / "stage_gates.json"
    gates.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(l3_preflight, "STAGE_GATES", gates)
    assert l3_preflight.check_stage_gates().startswith("stage_gates_unparseable")


def test_missing_gate_keys_fails(monkeypatch, tmp_path):
    gates = tmp_path / "stage_gates.json"
    gates.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    monkeypatch.setattr(l3_preflight, "STAGE_GATES", gates)
    assert l3_preflight.check_stage_gates().startswith("stage_gates_missing_keys")


def test_empty_impact_sets_fails(monkeypatch, tmp_path):
    gates = tmp_path / "stage_gates.json"
    gates.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "levels": {},
                "impact_sets": {},
                "stage_gates": {},
                "force_l3_triggers": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(l3_preflight, "STAGE_GATES", gates)
    assert l3_preflight.check_stage_gates() == "stage_gates_impact_sets_empty"
