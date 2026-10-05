"""Qualification runner must reject missing main gates and altered source bytes."""
import hashlib
import json

import pytest

from tools.run_lookup_rescue_support import CASE_IDS, MAIN, load_sources, replay, validate_main_gate


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


def test_runner_replays_four_synthetic_bodies_without_publication_authority():
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
        cases.append({"id": name, "query": "Python 3.14什么时候发布", "sources": sources})
    rows = replay(cases)
    assert len(rows) == 4
    assert all(row["publication"]["status"] == "abstained" for row in rows)
    assert all(row["dangerous_publish"] == 0 for row in rows)
    assert all(row["sources"][0]["kind"] == "synthetic_development" for row in rows)
