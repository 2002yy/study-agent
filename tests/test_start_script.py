import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "start-study-agent.ps1"
IDENTITY_HELPER = ROOT / "tools" / "frontend-identity.ps1"
ARGUMENT_HELPER = ROOT / "tools" / "child-arguments.ps1"
FRONTEND_ENTRY = ROOT / "frontend" / "index.html"

FOREIGN_PAGES = {
    "vite-default": (
        "<!doctype html><html><head><title>Vite + React + TS</title></head>"
        '<body><div id="root"></div></body></html>'
    ),
    "nginx-welcome": (
        "<html><head><title>Welcome to nginx!</title></head>"
        "<body><h1>Welcome to nginx!</h1></body></html>"
    ),
    "api-json": '{"detail":"Unauthorized"}',
    # A hyphen is a word boundary, so `data-name` used to satisfy a `\bname`
    # pattern even though it declares nothing.
    "hyphenated-attributes": (
        "<!doctype html><html><head><title>学习助手 · 学习工作台</title>"
        '<meta data-name="study-agent-app" data-content="study-agent" />'
        '</head><body><div id="root"></div></body></html>'
    ),
    # A comment that documents the marker is not a declaration either.
    "marker-in-a-comment": (
        "<!doctype html><html><head><title>学习助手 · 学习工作台</title>"
        '<!-- <meta name="study-agent-app" content="study-agent" /> -->'
        '</head><body><div id="root"></div></body></html>'
    ),
    # `<meta` is a tag name, not a prefix: this is a different element.
    "meta-data-element": (
        "<!doctype html><html><head><title>学习助手 · 学习工作台</title>"
        '<meta-data name="study-agent-app" content="study-agent"></meta-data>'
        '</head><body><div id="root"></div></body></html>'
    ),
}


def test_start_script_does_not_embed_api_token_in_child_command():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "$tokenQuoted" not in text
    assert "VITE_STUDY_AGENT_API_TOKEN='$tokenQuoted'" not in text
    assert "inherit" in text.lower()


def test_start_script_never_hands_the_token_to_vite():
    """Vite exposes every VITE_* variable to client code: the secret stays out."""

    text = SCRIPT.read_text(encoding="utf-8")

    assert "$env:VITE_STUDY_AGENT_API_TOKEN =" not in text
    assert "Remove-Item Env:VITE_STUDY_AGENT_API_TOKEN" in text


def test_opened_browser_receives_the_token_in_the_url_fragment_only():
    """A fragment never reaches the server or a Referer, so it is the one safe
    place to hand a token to the page the launcher opens."""

    text = SCRIPT.read_text(encoding="utf-8")

    assert '"/#token" + "="' in text
    assert "[uri]::EscapeDataString" in text
    assert "Start-Process $openUrl" in text


def test_start_script_probes_providers_with_the_token_or_says_it_is_missing():
    text = SCRIPT.read_text(encoding="utf-8")

    assert '-Headers $probeHeaders' in text
    assert "未配置 API 令牌" in text


def test_start_script_uses_npm_cmd_and_checks_service_identity():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "Get-Command npm.cmd" in text
    assert "Test-BackendIdentity" in text
    assert 'health.service -eq "study-agent"' in text
    assert "Test-FrontendIdentity" in text


def test_start_script_reuses_loopback_searxng_and_prints_acceptance_summary():
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'Join-Path $PSScriptRoot "manage-searxng.ps1"' in text
    assert "& $manager -Action Ensure" in text
    assert '"http://127.0.0.1:8080/healthz"' in text
    assert '"$BackendUrl/health/providers?probe=true"' in text
    assert "人工检查清单" in text
    assert "MOBILE_ACCEPTANCE_D4D.md" in text


def test_frontend_identity_does_not_key_on_the_page_title():
    """The old check matched a hardcoded English <title> that went stale.

    Identity must come from an explicit marker, and the launcher must run the
    same helper the tests run instead of carrying its own copy of the rule.
    """

    launcher = SCRIPT.read_text(encoding="utf-8")

    assert "Study Agent Console" not in launcher
    assert 'frontend-identity.ps1' in launcher
    assert "Test-StudyAgentFrontendContent" in launcher


def test_frontend_entry_declares_the_identity_marker():
    entry = FRONTEND_ENTRY.read_text(encoding="utf-8")

    assert 'name="study-agent-app"' in entry
    assert 'content="study-agent"' in entry


def powershell_exe() -> str:
    for name in ("pwsh", "powershell"):
        path = shutil.which(name)
        if path:
            return path
    return None


def powershell_arguments(powershell: str, harness: Path) -> list[str]:
    """`-ExecutionPolicy` only exists on Windows; pwsh on Linux rejects it."""

    arguments = [powershell, "-NoProfile"]
    if sys.platform == "win32":
        arguments += ["-ExecutionPolicy", "Bypass"]
    arguments += ["-File", str(harness)]
    return arguments


def judge_frontend_page(page: Path, workdir: Path) -> str:
    """Run the launcher's own predicate against a page and return its verdict."""

    powershell = powershell_exe()
    if powershell is None:
        pytest.skip("PowerShell is not available on this machine")

    harness = workdir / "frontend-identity-probe.ps1"
    harness.write_text(
        ". '" + str(IDENTITY_HELPER).replace("'", "''") + "'\n"
        "$content = Get-Content -Raw -LiteralPath '"
        + str(page).replace("'", "''")
        + "' -Encoding UTF8\n"
        "if (Test-StudyAgentFrontendContent -Content $content) { 'accepted' } else { 'rejected' }\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        powershell_arguments(powershell, harness),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


def test_frontend_identity_accepts_the_real_entry_page(tmp_path):
    assert judge_frontend_page(FRONTEND_ENTRY, tmp_path) == "accepted"


def test_frontend_identity_accepts_the_marker_in_any_attribute_order(tmp_path):
    page = tmp_path / "reordered.html"
    page.write_text(
        "<!doctype html><html><head>"
        "<meta content='study-agent' name='study-agent-app'>"
        "</head><body><div id=\"root\"></div></body></html>",
        encoding="utf-8",
    )

    assert judge_frontend_page(page, tmp_path) == "accepted"


@pytest.mark.parametrize("label", sorted(FOREIGN_PAGES))
def test_frontend_identity_rejects_unrelated_pages(label, tmp_path):
    page = tmp_path / f"{label}.html"
    page.write_text(FOREIGN_PAGES[label], encoding="utf-8")

    assert judge_frontend_page(page, tmp_path) == "rejected"


def test_frontend_identity_rejects_a_page_that_only_copies_the_title(tmp_path):
    page = tmp_path / "title-only.html"
    page.write_text(
        "<!doctype html><html><head><title>学习助手 · 学习工作台</title></head>"
        '<body><div id="root"></div></body></html>',
        encoding="utf-8",
    )

    assert judge_frontend_page(page, tmp_path) == "rejected"


def test_start_script_quotes_child_arguments_with_spaces():
    """`Start-Process -ArgumentList <array>` joins with spaces and drops quotes.

    With this repository checked out under a path containing a space, the Vite
    entry point arrived as two arguments (`Cannot find module
    'C:\\Users\\Zhang\\Desktop\\study'`). The launcher must build the command
    line through the shared helper instead of handing the raw array over.
    """

    text = SCRIPT.read_text(encoding="utf-8")

    assert "child-arguments.ps1" in text
    assert "ConvertTo-ChildArgumentLine" in text
    assert "-ArgumentList $Arguments" not in text


def test_child_argument_line_quotes_a_path_with_spaces(tmp_path):
    powershell = powershell_exe()
    if powershell is None:
        pytest.skip("PowerShell is not available on this machine")

    harness = tmp_path / "child-arguments-probe.ps1"
    harness.write_text(
        ". '" + str(ARGUMENT_HELPER).replace("'", "''") + "'\n"
        "ConvertTo-ChildArgumentLine @(\n"
        "  'C:\\Users\\Zhang\\Desktop\\study agent\\frontend\\node_modules\\vite\\bin\\vite.js',\n"
        "  '--host',\n"
        "  '127.0.0.1'\n"
        ")\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        powershell_arguments(powershell, harness),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    line = result.stdout.strip().splitlines()[-1]
    # The spaced path is one quoted argument; plain arguments stay untouched.
    assert '"C:\\Users\\Zhang\\Desktop\\study agent\\frontend\\node_modules\\vite\\bin\\vite.js"' in line
    assert "--host 127.0.0.1" in line
    # Negative control: the raw join is exactly the shape that broke Node.
    assert line != (
        "C:\\Users\\Zhang\\Desktop\\study agent\\frontend\\node_modules\\vite\\bin\\vite.js"
        " --host 127.0.0.1"
    )
