from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "start-study-agent.ps1"


def test_start_script_does_not_embed_api_token_in_child_command():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "$tokenQuoted" not in text
    assert "VITE_STUDY_AGENT_API_TOKEN='$tokenQuoted'" not in text
    assert "inherit" in text.lower()


def test_start_script_uses_npm_cmd_and_checks_service_identity():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "Get-Command npm.cmd" in text
    assert "Test-BackendIdentity" in text
    assert 'health.service -eq "study-agent"' in text
    assert "Test-FrontendIdentity" in text
