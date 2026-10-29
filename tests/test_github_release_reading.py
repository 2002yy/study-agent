"""``/releases`` must be read as releases, not as repository metadata.

Search-2 found the gap: "what is the latest release" read the README and the
file list, so the release tag and date were never in the text.
"""

from __future__ import annotations

from src.web import github_reader
from src.web.github_reader import GitHubSourceReader, parse_github_url


def test_release_urls_parse_into_a_release_target():
    listing = parse_github_url("https://github.com/vllm-project/vllm/releases")
    latest = parse_github_url("https://github.com/vllm-project/vllm/releases/latest")
    tagged = parse_github_url("https://github.com/vllm-project/vllm/releases/tag/v0.6.3")

    assert listing is not None and (listing.kind, listing.tag) == ("releases", "")
    assert latest is not None and (latest.kind, latest.tag) == ("releases", "latest")
    assert tagged is not None and (tagged.kind, tagged.tag) == ("releases", "v0.6.3")


def test_release_listing_becomes_text_with_the_tag_and_date(monkeypatch):
    requested: list[str] = []

    def fake_request_json(url: str, **_kwargs):
        requested.append(url)
        assert "/releases" in url
        return [
            {
                "tag_name": "v0.6.3",
                "name": "v0.6.3",
                "published_at": "2025-08-12T10:00:00Z",
                "prerelease": False,
                "html_url": "https://github.com/vllm-project/vllm/releases/tag/v0.6.3",
            },
            {
                "tag_name": "v0.6.2",
                "name": "",
                "published_at": "2025-07-30T10:00:00Z",
                "prerelease": False,
                "html_url": "https://github.com/vllm-project/vllm/releases/tag/v0.6.2",
            },
        ]

    monkeypatch.setattr(github_reader, "_request_json", fake_request_json)

    result = GitHubSourceReader().read("https://github.com/vllm-project/vllm/releases")

    assert result["ok"] is True
    assert result["kind"] == "releases"
    assert result["latest"] == "v0.6.3"
    assert [row["tag"] for row in result["releases"]] == ["v0.6.3", "v0.6.2"]
    assert "v0.6.3" in result["content"]
    assert "2025-08-12" in result["content"]
    assert "Latest release: v0.6.3" in result["content"]
    assert len(requested) == 1


def test_a_specific_tag_reads_that_tag_not_the_repository(monkeypatch):
    requested: list[str] = []

    def fake_request_json(url: str, **_kwargs):
        requested.append(url)
        return {
            "tag_name": "v0.5.0",
            "name": "v0.5.0",
            "published_at": "2025-01-05T00:00:00Z",
            "prerelease": False,
            "html_url": "https://github.com/vllm-project/vllm/releases/tag/v0.5.0",
        }

    monkeypatch.setattr(github_reader, "_request_json", fake_request_json)

    result = GitHubSourceReader().read(
        "https://github.com/vllm-project/vllm/releases/tag/v0.5.0"
    )

    assert result["latest"] == "v0.5.0"
    assert "releases/tags/v0.5.0" in requested[0]


def test_a_repository_without_releases_says_so_instead_of_falling_back(monkeypatch):
    monkeypatch.setattr(github_reader, "_request_json", lambda url, **_: [])

    result = GitHubSourceReader().read("https://github.com/openai/example/releases")

    assert result["ok"] is True
    assert result["latest"] is None
    assert "no published releases" in result["content"]
