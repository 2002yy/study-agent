from dataclasses import replace

import pytest

from src.web.research import official_resolver as resolver
from src.web.research.evidence_binding import document_from_read
from src.web.research.identity import resolve_identity
from src.web.research.official_publication import publish_official_fields
from src.web.research.release_date import extract_release_date, normalize_release_date
from src.web.research_recovery import recover_public_research
from src.web.tool_gateway import GeneralWebGateway
from tests.test_official_source_quality import metadata


URL = "https://www.python.org/downloads/release/python-3140/"


@pytest.mark.parametrize("query", ["Python 3.14最新正式版发布变化", "Python 3.14.x发布变化",
                                  "Python 3.14.0rc1发布时间"])
def test_family_or_prerelease_intent_is_not_reinterpreted_as_initial_stable(query):
    assert resolver.official_plan(query) is None


@pytest.mark.parametrize("label", ["Release date:", "Release Date:", "release date:"])
def test_date_label_case_does_not_change_verified_field(label):
    fields = resolver._fields(URL, f"<h1>Python 3.14.0</h1><p><strong>{label}</strong> Oct. 7, 2025</p>".encode())
    assert fields["release_date"] == "2025-10-07"


@pytest.mark.parametrize("value,result", [("Oct. 7, 2025", "2025-10-07"),
    ("October 7, 2025", "2025-10-07"), ("2024-02-29", "2024-02-29"),
    ("Feb. 29, 2025", None), ("2025-02-30", None), ("07/10/2025", None),
    ("Octoberish 7, 2025", None), ("sometime in October", None)])
def test_date_validation_never_guesses(value, result):
    assert normalize_release_date(value) == result


@pytest.mark.parametrize("body", [
    "<p>No release date provided.</p>", "<p>Release date: Feb. 30, 2025</p>",
    "<h2>Python 3.13.0</h2><p>Release date: Oct. 7, 2024</p>",
    "<p>Release date: Oct. 7, 2025</p><p>Release date: Oct. 8, 2025</p>",
])
def test_missing_invalid_adjacent_or_ambiguous_dates_are_not_filled(body):
    assert "release_date" not in resolver._fields(URL, ("<h1>Python 3.14.0</h1>" + body).encode())


def test_different_release_heading_cannot_use_requested_url():
    with pytest.raises(ValueError, match="identity_mismatch"):
        resolver._fields(URL, b"<h1>Python 3.14.1</h1><p>Release date: Oct. 7, 2025</p>")


@pytest.mark.parametrize("version", ["3.14.0rc1", "3.14.0a1", "3.14.0.1"])
def test_prerelease_or_extended_heading_is_not_truncated_to_stable(version):
    with pytest.raises(ValueError, match="identity_mismatch"):
        resolver._fields(URL, f"<h1>Python {version}</h1><p>Release date: Oct. 7, 2025</p>".encode())


def test_bound_date_has_actual_read_span_and_quote():
    document = document_from_read("read-date", URL,
                                  b"<h1>Python 3.14.0</h1><p>Release date: Oct. 7, 2025</p>")
    identity = resolve_identity("python", "3.14")
    assert identity is not None
    field = extract_release_date(document, identity)
    assert field is not None
    proposal = field.binding.proposal
    start, end = proposal.evidence_span
    assert document.text[start:end] == proposal.quote == "Release date: Oct. 7, 2025"
    assert extract_release_date(replace(document, text=document.text + "tampered"), identity) is None


def test_python_short_version_reads_official_date_without_search_or_model(monkeypatch):
    metadata(monkeypatch, b"<h1>Python 3.14.0</h1><p>Release date: Oct. 7, 2025</p>")
    gateway = GeneralWebGateway()
    monkeypatch.setattr(gateway, "search_exact", lambda *args, **kwargs: pytest.fail("official identity must avoid rescue"))
    query = "Python 3.14什么时候发布"
    calls = recover_public_research(gateway, query)
    reads = [call for call in calls if call.get("name") == "web_read"]
    assert len(reads) == 1
    assert reads[0]["result"].get("answer_eligible") is not False
    answer, audit = publish_official_fields(query, calls, "An invented date")
    assert "2025-10-07" in answer and "invented" not in answer
    assert audit["status"] == "field_backed"
    date_ref = next(ref for ref in audit["assertion_refs"] if ref["field"] == "release_date")
    binding = date_ref["source_binding"]
    assert binding["quote"] == "Release date: Oct. 7, 2025"
    assert binding["heading_quote"] == "Python 3.14.0"
    assert binding["version"] == "3.14.0"


def test_candidate_flag_or_wrong_product_cannot_bypass_marker(monkeypatch):
    metadata(monkeypatch, b"<h1>Python 3.14.0</h1><p>Release date: Oct. 7, 2025</p>")
    result = resolver.read_official_metadata(URL, timeout=1, max_chars=5000)
    assert result is not None
    plan = resolver.official_plan("Python 3.14什么时候发布")
    assert plan is not None and resolver.verified_python_identity(plan, URL, result)
    assert not resolver.verified_python_identity(plan, URL, {"identity_verified": True})
    assert not resolver.verified_python_identity(plan, URL, {**result, "source_version": "3.14.1"})
    assert not resolver.verified_python_identity(plan, URL, {**result, "content": "changed"})
