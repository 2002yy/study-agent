"""Release semantics and the read budget of the GitHub reader.

Three product rules are pinned here:
- ``/releases/latest`` asks GitHub for the latest *stable* release;
- ``/releases/tag/<tag>`` never claims that tag is the latest;
- the timeout the caller passes is the budget the reader actually uses, and a
  missed deadline is a named failure, not a silent repository read.
"""

from __future__ import annotations

import io
import socket
import time
from urllib.error import HTTPError

from src.web import github_reader
from src.web.github_reader import GitHubSourceReader, parse_github_url
from src.web.tool_gateway import GeneralWebGateway


def _release(tag: str, *, prerelease: bool = False, date: str = "2026-10-01T00:00:00Z"):
    return {
        "tag_name": tag,
        "name": tag,
        "published_at": date,
        "prerelease": prerelease,
        "html_url": f"https://github.com/o/r/releases/tag/{tag}",
    }


def test_latest_uses_the_dedicated_endpoint_and_reports_the_stable_release(monkeypatch):
    requested: list[str] = []

    def fake_request_json(url: str, **_kwargs):
        requested.append(url)
        return _release("v2.0.0")

    monkeypatch.setattr(github_reader, "_request_json", fake_request_json)

    result = GitHubSourceReader().read("https://github.com/o/r/releases/latest")

    assert requested == ["https://api.github.com/repos/o/r/releases/latest"]
    assert result["latest"] == "v2.0.0"
    assert "Latest stable release: v2.0.0" in result["content"]
    assert "Newest release" not in result["content"]


def test_a_missing_latest_is_reported_as_no_release_not_as_an_http_error(monkeypatch):
    def fake_request_json(url: str, **_kwargs):
        raise HTTPError(url, 404, "Not Found", None, io.BytesIO(b""))

    monkeypatch.setattr(github_reader, "_request_json", fake_request_json)

    result = GitHubSourceReader().read("https://github.com/o/r/releases/latest")

    assert result["ok"] is True
    assert result["latest"] is None
    assert "no published releases" in result["content"]


def test_the_listing_separates_stable_from_prerelease_and_does_not_call_it_latest(monkeypatch):
    def fake_request_json(url: str, **_kwargs):
        return [_release("v3.0.0-rc1", prerelease=True), _release("v2.9.0")]

    monkeypatch.setattr(github_reader, "_request_json", fake_request_json)

    result = GitHubSourceReader().read("https://github.com/o/r/releases")

    assert result["newest"] == "v3.0.0-rc1"
    assert result["latest"] == "v2.9.0"
    assert "[prerelease]" in result["content"]
    assert "Newest release: v3.0.0-rc1" in result["content"]
    assert "Latest stable release: v2.9.0" in result["content"]


def test_a_specific_tag_is_requested_never_latest(monkeypatch):
    monkeypatch.setattr(
        github_reader, "_request_json", lambda url, **_: _release("v0.5.0")
    )

    result = GitHubSourceReader().read(
        "https://github.com/o/r/releases/tag/v0.5.0"
    )

    assert result["requested"] == "v0.5.0"
    assert result["latest"] is None
    assert "Requested release: v0.5.0" in result["content"]
    assert "Latest" not in result["content"]


def test_the_gateway_passes_the_read_timeout_to_the_github_reader():
    captured: dict[str, object] = {}

    class FakeReader:
        def supports(self, _url):
            return True

        def read(self, url, *, max_chars=12000, timeout=None):
            captured.update({"url": url, "timeout": timeout})
            return {"ok": True, "content": "x"}

    gateway = GeneralWebGateway(github_reader=FakeReader())
    gateway.read("https://github.com/o/r/releases", timeout=6.0)

    assert captured["timeout"] == 6.0


def test_a_release_read_gets_the_dedicated_default_budget_when_none_is_given(monkeypatch):
    captured: dict[str, object] = {}

    class FakeReader:
        def supports(self, _url):
            return True

        def read(self, url, *, max_chars=12000, timeout=None):
            captured["timeout"] = timeout
            return {"ok": True, "content": "x"}

    monkeypatch.setenv("WEB_GITHUB_RELEASES_TIMEOUT_SECONDS", "18")
    gateway = GeneralWebGateway(github_reader=FakeReader())
    gateway.read("https://github.com/o/r/releases")

    assert 17.9 <= float(captured["timeout"]) <= 18.0


def test_an_explicit_timeout_beats_the_release_default(monkeypatch):
    captured: dict[str, object] = {}

    class FakeReader:
        def supports(self, _url):
            return True

        def read(self, url, *, max_chars=12000, timeout=None):
            captured["timeout"] = timeout
            return {"ok": True, "content": "x"}

    monkeypatch.setenv("WEB_GITHUB_RELEASES_TIMEOUT_SECONDS", "18")
    gateway = GeneralWebGateway(github_reader=FakeReader())
    gateway.read("https://github.com/o/r/releases", timeout=6.0)

    assert 5.9 <= float(captured["timeout"]) <= 6.0


def test_a_socket_timeout_is_reported_as_github_read_timeout(monkeypatch):
    def slow_request(*_args, **_kwargs):
        raise socket.timeout("timed out")

    monkeypatch.setattr(github_reader, "_request_bytes", slow_request)

    result = GitHubSourceReader().read(
        "https://github.com/o/r/releases/latest", timeout=1
    )

    assert result["ok"] is False
    assert result["error"] == "github_read_timeout"


def test_the_deadline_stops_before_the_next_request(monkeypatch):
    calls: list[str] = []

    def slow_bytes(url, **_kwargs):
        calls.append(url)
        time.sleep(0.6)
        return b'{"default_branch": "main"}'

    monkeypatch.setattr(github_reader, "_request_bytes", slow_bytes)

    result = GitHubSourceReader().read("https://github.com/o/r", timeout=1)

    # Two requests fit in the one-second budget; the third must not start.
    assert result["ok"] is False
    assert result["error"] == "github_read_timeout"
    assert len(calls) == 2


def test_rate_limiting_is_its_own_error(monkeypatch):
    def limited(url, **_kwargs):
        raise HTTPError(
            url, 403, "Forbidden", {"X-RateLimit-Remaining": "0"}, io.BytesIO(b"")
        )

    monkeypatch.setattr(github_reader, "_request_json", limited)

    result = GitHubSourceReader().read("https://github.com/o/r/releases")

    assert result["error"] == "github_rate_limited"


def test_release_urls_parse_into_a_release_target():
    listing = parse_github_url("https://github.com/vllm-project/vllm/releases")
    latest = parse_github_url("https://github.com/vllm-project/vllm/releases/latest")
    tagged = parse_github_url("https://github.com/vllm-project/vllm/releases/tag/v0.6.3")

    assert listing is not None and (listing.kind, listing.tag) == ("releases", "")
    assert latest is not None and (latest.kind, latest.tag) == ("releases", "latest")
    assert tagged is not None and (tagged.kind, tagged.tag) == ("releases", "v0.6.3")
