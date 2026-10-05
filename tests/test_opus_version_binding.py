from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from src.application.chat_service import ChatCommand
from src.web.research import official_resolver as resolver
from src.web.research.evidence_binding import document_from_read
from src.web.research.official_publication import publish_official_fields
from src.web.research_recovery import recover_public_research, recovery_summary
from src.web.tool_gateway import GeneralWebGateway
from tests.test_chat_service import _service
from tests.test_official_source_quality import metadata


URL = "https://platform.claude.com/docs/en/models/opus-5-5/overview"
INTRO = "For long-running agentic coding and knowledge work"


def payload(heading="Claude Opus <span>5.5</span><span>Latest</span>", intro=INTRO,
            model_id="claude-opus-5-5", extra=""):
    return (f"<h1>{heading}</h1><p>{intro}</p><button>{model_id}</button>"
            f"<h2>How it compares</h2><table><tr><td>Claude Opus 5.1</td>"
            f"<td>Old capability, never use for 5.5</td></tr></table>{extra}").encode()


def test_heading_badges_preserve_version_boundaries():
    document = document_from_read("one", URL, payload())
    section = document.sections[0]
    assert "5.5 Latest" in " ".join(document.text[section.heading_start:section.heading_end].split())
    assert "5.5Latest" not in document.text


def test_exact_page_is_the_registered_seed():
    plan = resolver.official_plan("Opus 5.5是什么")
    assert plan is not None and plan.urls == (URL,)
    assert resolver.valid_candidate("Opus 5.5是什么", URL)
    assert not resolver.valid_candidate("Opus 5.5是什么", "https://platform.claude.com/docs/en/models/overview")


@pytest.mark.parametrize("query", ["Opus 5.5与5.1有什么区别", "Opus 5.5rc1是什么", "Opus 5.5+local是什么",
                                  "Opus 5.5.1.2是什么", "Opus 5.5-rc1是什么"])
def test_comparisons_or_extended_tokens_are_not_single_version_lookups(query):
    assert resolver.official_plan(query) is None


def test_only_bound_intro_is_extracted_and_audited():
    bindings = {}
    data = payload()
    fields = resolver._fields(URL, data, source_bindings=bindings)
    assert fields == {"project": "Claude Opus", "version": "5.5", "official_positioning": INTRO}
    document = document_from_read(hashlib.sha256(data).hexdigest(), URL, data)
    binding = bindings["official_positioning"]
    start, end = binding["source_span"]
    assert document.text[start:end] == binding["quote"] == INTRO
    start, end = binding["model_id_span"]
    assert document.text[start:end] == binding["model_id"] == "claude-opus-5-5"
    assert binding["decoded_payload_sha256"] == hashlib.sha256(data).hexdigest()
    assert "Old capability" not in str(fields)


@pytest.mark.parametrize("heading", ["Claude Opus 5.1", "Claude Opus 5.5.1", "Claude Opus 5.5rc1",
                                    "Claude Opus 5.5 and Claude Opus 5.1", "Unknown model", "Claude Opus 5.5+local"])
def test_wrong_ambiguous_or_extended_heading_cannot_bind(heading):
    with pytest.raises(ValueError, match="identity_mismatch"):
        resolver._fields(URL, payload(heading=heading))


@pytest.mark.parametrize("model_id", ["", "claude-opus-5-1", "claude-opus-5-5-20261005",
                                     "claude-opus-5-5extended", "claude-opus-5-5+local"])
def test_model_id_must_match_complete_exact_version(model_id):
    with pytest.raises(ValueError, match="id_identity_mismatch"):
        resolver._fields(URL, payload(model_id=model_id))


@pytest.mark.parametrize("intro", ["Claude Opus 5.1 is powerful", "Opus 5.5 versus Opus 5.1",
                                  "claude-opus-5-5", "Compared to the previous model", "Claude Fable 5.1 is powerful"])
def test_mixed_version_or_comparison_intro_is_not_positioning(intro):
    with pytest.raises(ValueError):
        resolver._fields(URL, payload(intro=intro))


def test_navigation_script_or_later_section_ids_cannot_validate_missing_intro_id():
    data = ("<nav>claude-opus-5-5</nav><h1>Claude Opus 5.5</h1>"
            f"<p>{INTRO}</p><script>claude-opus-5-5</script>"
            "<h2>IDs</h2><button>claude-opus-5-5</button>").encode()
    with pytest.raises(ValueError, match="id_identity_mismatch"):
        resolver._fields(URL, data)


@pytest.mark.parametrize("other", ["claude-opus-5-1", "claude-opus-5-5+local", "claude-opus-5-5extended"])
def test_valid_id_does_not_hide_a_second_mismatching_or_unsupported_token(other):
    data = payload().replace(b"<h2>", f"<button>{other}</button><h2>".encode(), 1)
    with pytest.raises(ValueError, match="id_identity_mismatch"):
        resolver._fields(URL, data)


def test_secondary_heading_cannot_replace_page_identity():
    data = payload().replace(b"<h1>", b"<h2>").replace(b"</h1>", b"</h2>")
    with pytest.raises(ValueError, match="title_identity_mismatch"):
        resolver._fields(URL, data)


def test_header_control_text_cannot_be_published_as_positioning():
    data = payload().replace(b"</h1>", b"</h1><div>Copy page</div>", 1)
    with pytest.raises(ValueError, match="intro_not_paragraph"):
        resolver._fields(URL, data)


def test_candidate_flag_wrong_version_or_digest_cannot_replace_marker(monkeypatch):
    metadata(monkeypatch, payload())
    result = resolver.read_official_metadata(URL, timeout=1, max_chars=6000)
    plan = resolver.official_plan("Opus 5.5是什么")
    assert plan is not None and result is not None
    assert resolver.verified_opus_identity(plan, URL, result)
    assert not resolver.verified_opus_identity(plan, URL, {"identity_verified": True})
    assert not resolver.verified_opus_identity(plan, URL, {**result, "source_version": "5.1"})
    assert not resolver.verified_opus_identity(plan, URL, {**result, "content": "tampered"})


def test_overview_remains_ineligible_even_with_target_heading():
    with pytest.raises(ValueError, match="version_scoped"):
        resolver._fields("https://platform.claude.com/docs/en/models/overview", payload())


def test_official_lookup_stops_after_one_read_and_publishes_only_bound_fields(monkeypatch, tmp_path):
    metadata(monkeypatch, payload())
    gateway = GeneralWebGateway()
    monkeypatch.setattr(gateway, "search_exact", lambda *args, **kwargs: pytest.fail("exact page is sufficient"))
    query = "Opus 5.5是什么"
    calls = recover_public_research(gateway, query)
    assert recovery_summary(calls)["reads"] == 1
    answer, audit = publish_official_fields(query, calls, "Opus 5.5 beats 5.1, invented benchmark")
    assert INTRO in answer and "invented" not in answer and "Old capability" not in answer
    assert audit["status"] == "field_backed"
    ref = next(ref for ref in audit["assertion_refs"] if ref["field"] == "official_positioning")
    assert ref["source_binding"]["version"] == "5.5"
    service, repository = _service(tmp_path)
    prepared = service.start_turn(ChatCommand(user_input=query, thread_id="opus-lookup"))
    prepared = replace(prepared, rag={**prepared.rag, "web_tools": {"enabled": True, "calls": calls}})
    completed = service.complete_turn(prepared, "Invented comparison: 5.5 is faster than 5.1")
    saved = repository.get_chat_turn(completed.id)
    assert INTRO in saved.assistant_message and "faster" not in saved.assistant_message
    assert saved.rag_snapshot["official_field_publication"]["status"] == "field_backed"


def test_redirect_to_a_different_model_cannot_keep_requested_identity(monkeypatch):
    class Response:
        headers = {}
        url = "https://platform.claude.com/docs/en/models/opus-5-1/overview"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            return payload()

    class Opener:
        def open(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(resolver, "build_opener", lambda *args: Opener())
    result = resolver.read_official_metadata(URL, timeout=1, max_chars=6000)
    assert result is not None and not result["ok"]
