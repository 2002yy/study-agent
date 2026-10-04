from dataclasses import replace

import pytest

from src.web.research.evidence_binding import EvidenceProposal, document_from_read, verify_binding
from src.web.research.identity import resolve_identity


@pytest.mark.parametrize("product,left,right,equal", [
    ("Python", "3.14", "3.14.0", True), ("Python", "3.14", "3.14.1", False),
    ("Python", "3.14.0rc1", "3.14.0", False), ("FastAPI", "0.115", "0.115.0", True),
    ("CUDA", "13", "13.0", True), ("GPT", "6", "6.1", False),
    ("Qwen", "3", "3.5", False), ("Opus", "5.1", "5.5", False),
])
def test_product_version_rules(product, left, right, equal):
    assert (resolve_identity(product, left) == resolve_identity(product, right)) is equal


@pytest.mark.parametrize("product,version", [("unknown", "3.14"), ("Python", "3"),
                                            ("Opus", "latest"), ("Python", "3.14.x")])
def test_unsupported_identity_remains_unknown(product, version):
    assert resolve_identity(product, version) is None


def sample(heading="Claude Opus 5.5", body="Target fact."):
    payload = (f"<h2>{heading}</h2><p>{body}</p>"
               "<h2>Claude Opus 5.1</h2><p>Adjacent fact.</p>").encode()
    document = document_from_read("read-1", "https://example.org/models", payload)
    identity = resolve_identity("Opus", "5.5")
    assert identity is not None
    start = document.text.index(body)
    section = document.sections[0]
    proposal = EvidenceProposal(identity, document.read_id, document.source_url, document.content_sha256,
                                (section.heading_start, section.heading_end), (start, start + len(body)), body)
    return document, proposal


def test_valid_binding_does_not_grant_fact_truth_or_official_authority():
    document, proposal = sample()
    binding = verify_binding(document, proposal)
    assert binding.status == "VERIFIED"
    assert binding.payload_sha256 == document.payload_sha256
    # Binding proves where the quote belongs; publication/support gates remain separate.


@pytest.mark.parametrize("change", [
    {"read_id": "other-read"}, {"source_url": "https://example.org/other"},
    {"content_sha256": "0" * 64}, {"quote": "Invented fact."}, {"heading_span": (0, 1)},
])
def test_model_cannot_forge_read_or_span(change):
    document, proposal = sample()
    assert verify_binding(document, replace(proposal, **change)).status == "UNKNOWN"


def test_adjacent_section_cannot_be_bound_to_target():
    document, proposal = sample()
    start = document.text.index("Adjacent fact.")
    assert verify_binding(document, replace(proposal, evidence_span=(start, start + 14),
                                            quote="Adjacent fact.")).status == "UNKNOWN"


@pytest.mark.parametrize("heading,body", [("Models overview", "Target fact."),
    ("Claude Opus 5.1", "Target fact."), ("Claude Opus 5.5 and Claude Opus 5.1", "Target fact."),
    ("Claude Opus 5.5", "Claude Opus 5.1 achieved this result.")])
def test_missing_ambiguous_or_mixed_identity_is_unknown(heading, body):
    document, proposal = sample(heading, body)
    assert verify_binding(document, proposal).status == "UNKNOWN"


def test_changed_reader_text_invalidates_binding():
    document, proposal = sample()
    assert verify_binding(replace(document, text=document.text + "changed"), proposal).status == "UNKNOWN"


def test_script_text_is_not_a_visible_version_anchor():
    document = document_from_read("r", "https://example.org/models",
                                  b'<h2>Overview<script>Claude Opus 5.5</script></h2><p>Fact.</p>')
    identity = resolve_identity("opus", "5.5")
    assert identity is not None
    section = document.sections[0]
    start = document.text.index("Fact.")
    proposal = EvidenceProposal(identity, "r", document.source_url, document.content_sha256,
                                (section.heading_start, section.heading_end), (start, start + 5), "Fact.")
    assert verify_binding(document, proposal).status == "UNKNOWN"


def test_nested_heading_ends_parent_scope_conservatively():
    document = document_from_read("r", "https://example.org/models",
                                  b'<h2>Claude Opus 5.5</h2><p>Fact.</p><h3>Comparison</h3><p>Other.</p>')
    identity = resolve_identity("opus", "5.5")
    assert identity is not None
    section = document.sections[0]
    start = document.text.index("Other.")
    proposal = EvidenceProposal(identity, "r", document.source_url, document.content_sha256,
                                (section.heading_start, section.heading_end), (start, start + 6), "Other.")
    assert verify_binding(document, proposal).status == "UNKNOWN"
