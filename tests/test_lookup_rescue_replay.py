"""Qualification runner must reject missing main gates and altered source bytes."""
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from tools import run_lookup_rescue_support as runner
from tools.run_lookup_rescue_support import (
    CASE_IDS, MAIN, load_sources, replay, validate_case_outcome, validate_main_gate, validate_replay_head,
)


def main_proof():
    return {"databaseId": 37314347931, "headSha": MAIN, "event": "push",
            "status": "completed", "conclusion": "success"}


@pytest.mark.parametrize("field,value", [("status", "in_progress"), ("headSha", "wrong_head"),
                                        ("conclusion", "failure"), ("event", "pull_request")])
def test_main_proof_must_be_exact_success(field, value):
    proof = main_proof()
    validate_main_gate(proof)
    proof[field] = value
    with pytest.raises(ValueError, match="exact-main success"):
        validate_main_gate(proof)


def test_source_bytes_cannot_be_changed_after_capture(tmp_path):
    payload = b"<p>Captured control</p>"
    (tmp_path / "payload.html").write_bytes(payload)
    source = {"payload_path": "payload.html", "payload_sha256": hashlib.sha256(payload).hexdigest(),
              "read_at": "2026-10-05T13:00:00Z", "kind": "captured_public_html"}
    manifest = {"cases": [{"id": name, "query": "Python 3.14什么时候发布",
                           "sources": [source] * (2 if name == "unbound_exhaustion" else 1)}
                          for name in sorted(CASE_IDS)]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert len(load_sources(path)) == 4
    (tmp_path / "payload.html").write_bytes(payload + b" altered")
    with pytest.raises(ValueError, match="digest mismatch"):
        load_sources(path)


def make_synthetic_cases():
    # Development smoke only: these generated HTML bodies are not source evidence.
    cases = []
    for name in sorted(CASE_IDS):
        versions = ["3.13", "3.15"] if name == "unbound_exhaustion" else ["3.14"]
        host = "realpython.com" if name == "nonofficial_direct" else "docs.python.org"
        sources = [{"url": f"https://{host}/{version}/tutorial/control.html",
                    "title": "Python 3.14 release", "kind": "synthetic_development",
                    "html": f"<article><h1>Python {version}</h1><p>"
                    + f"Python {version} language tutorial and examples. " * 20 + "</p></article>"}
                   for version in versions]
        if name == "related_missing_field":
            sources[0]["html"] = ("<article><h1>Language tutorial</h1><p>"
                                  + "This page explains language syntax and examples. " * 20
                                  + "</p></article>")
        cases.append({"id": name, "query": "Python 3.14什么时候发布", "sources": sources})
    return cases


@pytest.fixture
def synthetic_cases():
    return make_synthetic_cases()


@pytest.fixture(scope="module")
def successful_rows():
    # Preserve the same four development-only inputs without network access.
    return replay(make_synthetic_cases())


def test_runner_replays_four_synthetic_bodies_without_publication_authority(successful_rows):
    rows = successful_rows
    assert len(rows) == 4
    assert all(row["publication"]["status"] == "abstained" for row in rows)
    assert all(row["dangerous_publish"] == 0 for row in rows)
    assert all(row["sources"][0]["kind"] == "synthetic_development" for row in rows)


def test_replay_head_must_descend_from_gated_main(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "Qualification test")
    git("config", "user.email", "qualification@example.invalid")
    git("commit", "--allow-empty", "-m", "older")
    older = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-m", "gated main")
    gated = git("rev-parse", "HEAD")
    monkeypatch.setattr(runner, "MAIN", gated)
    git("commit", "--allow-empty", "-m", "replay descendant")
    validate_replay_head(git("rev-parse", "HEAD"), tmp_path)
    with pytest.raises(ValueError, match="must contain"):
        validate_replay_head(older, tmp_path)
    git("checkout", "--orphan", "unrelated")
    git("commit", "--allow-empty", "-m", "unrelated root")
    with pytest.raises(ValueError, match="must contain"):
        validate_replay_head(git("rev-parse", "HEAD"), tmp_path)


@pytest.mark.parametrize("case_id", sorted(CASE_IDS))
@pytest.mark.parametrize("mutation", ["status", "reads", "evidence", "body"])
def test_wrong_case_outcome_is_rejected(successful_rows, case_id, mutation):
    row = next(row for row in successful_rows if row["id"] == case_id)
    summary = dict(row["summary"])
    calls = row["raw_calls"]
    if mutation == "status":
        summary["status"] = "failed"
    elif mutation == "reads":
        summary["reads"] -= 1
    elif mutation == "body":
        calls = []
    elif case_id in {"unbound_exhaustion", "related_missing_field"}:
        calls = next(row for row in successful_rows if row["id"] == "alternate_official")["raw_calls"]
    else:
        calls = []
    with pytest.raises(ValueError, match="required recovery outcome"):
        validate_case_outcome(case_id, summary, calls)


def test_all_reader_failure_cannot_pass_replay(synthetic_cases, monkeypatch):
    from src.news.readers import local_reader

    monkeypatch.setattr(local_reader, "read_html_locally",
                        lambda *_a: SimpleNamespace(text="", method="failed_control", author=""))
    with pytest.raises(ValueError, match="required recovery outcome"):
        replay(synthetic_cases)


@pytest.mark.parametrize("failure", ["older_head", "all_readers"])
def test_cli_rejects_before_writing_artifact(tmp_path, synthetic_cases, monkeypatch, failure):
    from src.news.readers import local_reader

    proof = tmp_path / "main-ci.json"
    proof.write_text(json.dumps(main_proof()), encoding="utf-8")
    output = tmp_path / "rejected-result.json"
    head = subprocess.check_output(["git", "rev-parse", f"{MAIN}^" if failure == "older_head" else "HEAD"],
                                   cwd=runner.ROOT, text=True).strip()
    monkeypatch.setattr(runner.subprocess, "check_output",
                        lambda args, **_kwargs: "" if args[1] == "status" else head)
    monkeypatch.setattr(runner, "load_sources", lambda _p: synthetic_cases)
    monkeypatch.setattr(local_reader, "read_html_locally",
                        lambda *_a: SimpleNamespace(text="", method="failed_control", author=""))
    monkeypatch.setattr(runner.sys, "argv", ["runner", "--manifest", "unused.json", "--main-ci", str(proof),
                                            "--output", str(output)])
    message = "must contain" if failure == "older_head" else "required recovery outcome"
    with pytest.raises(ValueError, match=message):
        runner.main()
    assert not output.exists()
