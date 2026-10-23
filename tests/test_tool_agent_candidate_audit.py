from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from tools.audit_tool_agent_candidates import audit_trace

URL = "https://example.org/chapter"


def read(**changes):
    return {
        "tool": "read_page",
        "url": URL,
        "confirmed": True,
        "eligible": True,
        "attempted": True,
        "succeeded": True,
        "failure_reason": "",
        **changes,
    }


def test_success_then_duplicate_refusal_preserves_the_first_success():
    report = audit_trace(
        {
            "candidate_trace": [
                read(),
                read(
                    attempted=False, succeeded=False, failure_reason="page_read_before"
                ),
            ]
        }
    )
    row = report["candidates"][0]
    assert row["succeeded"] == row["attempted"] == 1
    assert row["read_actions"] == 2
    assert row["observed_gap"] == "body_support_unreviewed"
    assert report["publication_authority"] is False


def test_unshown_target_does_not_imply_it_was_missing_from_raw_links():
    row = audit_trace({"candidate_trace": []}, [URL])["candidates"][0]
    assert row["raw"] is None and row["filtered"] is None
    assert row["confirmed"] is None
    assert row["observed_gap"] == "not_shown_raw_and_filtered_unknown"


def test_old_record_has_unknown_visibility_and_is_not_a_zero_discovery_claim():
    result = audit_trace(
        {
            "calls": [
                {"action": {"tool": "read_page", "url": URL}, "result": {"ok": True}}
            ]
        },
        [URL],
    )
    assert result["candidate_trace_observed"] is False
    assert result["candidates"][0]["shown"] is None
    assert result["candidates"][0]["observed_gap"] == "candidate_visibility_unobserved"
    assert result["candidates"][0]["read_actions"] == 1
    assert result["candidates"][0]["attempted"] is None
    assert result["candidates"][0]["succeeded"] is None


def test_confirmed_but_ineligible_is_not_a_reader_failure():
    row = audit_trace(
        {
            "candidate_trace": [
                read(
                    eligible=False,
                    attempted=False,
                    succeeded=False,
                    failure_reason="entry_not_eligible:off_topic",
                )
            ]
        }
    )["candidates"][0]
    assert row["confirmed"] is True
    assert row["observed_gap"] == "eligibility_rejected"
    assert row["attempted"] == 0


def test_guessed_url_and_quota_exhaustion_are_distinct():
    guessed = audit_trace(
        {
            "candidate_trace": [
                read(confirmed=False, eligible=False, attempted=False, succeeded=False)
            ]
        }
    )["candidates"][0]
    quota = audit_trace(
        {
            "candidate_trace": [
                read(attempted=False, succeeded=False, failure_reason="read_quota")
            ]
        }
    )["candidates"][0]
    assert guessed["observed_gap"] == "confirmation_rejected"
    assert quota["observed_gap"] == "read_not_attempted"


def test_http_failure_and_never_chosen_candidate_are_distinct():
    failed = audit_trace(
        {"candidate_trace": [read(succeeded=False, failure_reason="http_403")]}
    )["candidates"][0]
    unused = audit_trace(
        {
            "candidate_trace": [
                {"tool": "follow", "shown": [URL], "newly_confirmed": [URL]}
            ]
        }
    )["candidates"][0]
    assert failed["observed_gap"] == "read_failed"
    assert unused["observed_gap"] == "shown_without_read_action"


def test_redirect_body_binds_only_to_recorded_chain_and_never_awards_q1():
    final = "https://example.org/canonical"
    row = audit_trace(
        {
            "candidate_trace": [read()],
            "source_chain": [{"entry_url": URL, "read_url": final}],
            "bodies": [
                {"url": final, "ok": True, "chars": 5, "text": "index"},
                {"url": "https://elsewhere.org/", "ok": True, "text": "answer"},
            ],
        }
    )["candidates"][0]
    assert len(row["bodies"]) == 1
    assert row["bodies"][0]["text_sha256"] == hashlib.sha256(b"index").hexdigest()
    assert row["bodies"][0]["q1_state"] is None


def test_preview_is_never_hashed_as_complete_same_run_evidence():
    row = audit_trace(
        {
            "candidate_trace": [read()],
            "bodies": [{"url": URL, "ok": True, "chars": 2000, "preview": "excerpt"}],
        }
    )["candidates"][0]
    assert row["bodies"][0]["same_run_full_text"] is False
    assert row["bodies"][0]["text_sha256"] is None


def test_changed_queries_with_same_results_are_counted_without_inventing_reads():
    result = audit_trace(
        {
            "candidate_trace": [
                {"tool": "search", "query": "one", "shown": [URL]},
                {"tool": "search", "query": "two", "shown": [URL]},
                {"tool": "search", "query": "empty", "shown": []},
            ]
        }
    )
    assert result["repeated_search_result_sets"] == 1
    assert result["candidates"][0]["read_actions"] == 0


def test_cli_pins_input_bytes_and_preserves_source(tmp_path):
    source = tmp_path / "record.json"
    source.write_text(json.dumps({"candidate_trace": [read()]}), encoding="utf-8")
    original = source.read_bytes()
    output = tmp_path / "audit.json"
    script = (
        Path(__file__).resolve().parents[1] / "tools/audit_tool_agent_candidates.py"
    )
    subprocess.run(
        [sys.executable, str(script), str(source), "--out", str(output)], check=True
    )
    assert (
        json.loads(output.read_text())["input"]["sha256"]
        == hashlib.sha256(original).hexdigest()
    )
    assert source.read_bytes() == original
    rejected = subprocess.run(
        [sys.executable, str(script), str(source), "--out", str(source)],
        capture_output=True,
    )
    assert rejected.returncode != 0
    assert source.read_bytes() == original
