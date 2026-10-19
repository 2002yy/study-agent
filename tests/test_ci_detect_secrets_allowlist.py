from pathlib import Path
import re


CI_WORKFLOW = Path(".github/workflows/ci.yml")
AUDIT_HASH = "ab" * 32
#: A 40-hex value in an evidence file: a frozen run's target commit.
COMMIT_SHA = "06e96286d98d76c38018ff972460f42528479723"


def _exclude_lines_pattern() -> re.Pattern[str]:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"--exclude-lines '([^']+)'", text)
    assert match is not None, "CI detect-secrets --exclude-lines pattern is missing"
    return re.compile(match.group(1))


def test_ci_detect_secrets_allows_only_named_research_audit_hashes() -> None:
    pattern = _exclude_lines_pattern()

    for field in (
        "fingerprint_sha256",
        "observation_sha256",
        "input_sha256",
        "response_sha256",
        "content_sha256",
    ):
        assert pattern.search(f'"{field}": "{AUDIT_HASH}"') is not None


def test_ci_detect_secrets_does_not_allow_arbitrary_sha256_fields() -> None:
    pattern = _exclude_lines_pattern()

    assert pattern.search(f'"arbitrary_sha256": "{AUDIT_HASH}"') is None
    assert pattern.search(f'"api_key": "{AUDIT_HASH}"') is None
    assert pattern.search(f'"token": "{AUDIT_HASH}"') is None


def test_ci_detect_secrets_allows_the_named_evidence_commit_field() -> None:
    """A frozen acceptance run pins its target commit by name."""

    pattern = _exclude_lines_pattern()

    assert pattern.search(f'"candidate_head": "{COMMIT_SHA}"') is not None


def test_ci_detect_secrets_does_not_allow_arbitrary_commit_like_fields() -> None:
    """Naming one field must not open a class of fields.

    The value is a real commit SHA, but the allowlist is by *name*: an unnamed
    40-hex field, a differently shaped key, or a credential-shaped one stays a
    finding.
    """

    pattern = _exclude_lines_pattern()

    assert pattern.search(f'"head": "{COMMIT_SHA}"') is None
    assert pattern.search(f'"target_commit": "{COMMIT_SHA}"') is None
    assert pattern.search(f'"api_key": "{COMMIT_SHA}"') is None
    assert pattern.search(f'"token": "{COMMIT_SHA}"') is None
    # ...and the 40-hex branch still demands lowercase hex.
    assert pattern.search('"candidate_head": "06E96286D98D76C38018FF972460F42528479723"') is None


def test_ci_detect_secrets_audit_hash_allowlist_requires_64_lowercase_hex() -> None:
    pattern = _exclude_lines_pattern()

    assert pattern.search('"input_sha256": "abc123"') is None
    assert pattern.search(f'"response_sha256": "{AUDIT_HASH.upper()}"') is None
