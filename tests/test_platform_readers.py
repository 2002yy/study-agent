from __future__ import annotations

from src.web import platform_readers
from src.web.tool_gateway import GeneralWebGateway


def test_hosts_are_detected():
    assert platform_readers.detect("https://news.ycombinator.com/item?id=1") == "hn"
    assert platform_readers.detect(
        "https://stackoverflow.com/questions/1/x"
    ) == "stackexchange"
    assert platform_readers.detect(
        "https://forum.godotengine.org/t/foo/123"
    ) == "discourse"
    assert platform_readers.detect(
        "https://openreview.net/forum?id=abc"
    ) == "openreview"
    assert platform_readers.detect("https://example.com/") == ""


def test_hacker_news_returns_the_story_and_nested_comments(monkeypatch):
    item = {
        "title": "SQLite WAL", "text": "<p>story body</p>",
        "children": [
            {"author": "a", "created_at": "2026-01-01", "text": "top comment",
             "children": [
                 {"author": "b", "created_at": "2026-01-02", "text": "nested", "children": []},
             ]},
        ],
    }
    monkeypatch.setattr(platform_readers, "_get_json", lambda url, timeout: item)
    result = platform_readers.read("https://news.ycombinator.com/item?id=42", timeout=5)
    assert result["ok"] is True
    assert result["method"] == "hn_api"
    assert result["comments"] == 2
    assert "story body" in result["content"]
    assert "nested" in result["content"]


def test_stackexchange_returns_question_and_answers(monkeypatch):
    def fake(url, timeout):
        if "/answers" in url:
            return {"items": [{"score": 9, "owner": {"display_name": "bob"},
                               "body": "<p>answer body</p>"}]}
        return {"items": [{"title": "How to WAL?", "body": "<p>question body</p>"}]}

    monkeypatch.setattr(platform_readers, "_get_json", fake)
    result = platform_readers.read(
        "https://stackoverflow.com/questions/123/how", timeout=5
    )
    assert result["ok"] is True
    assert result["answers"] == 1
    assert "question body" in result["content"] and "answer body" in result["content"]


def test_discourse_returns_posts_and_next_page(monkeypatch):
    data = {
        "title": "Physics conveyor",
        "post_stream": {
            "posts": [
                {"username": "a", "created_at": "2026-01-01", "cooked": "<p>first</p>"},
                {"username": "b", "created_at": "2026-01-02", "cooked": "<p>second</p>"},
            ],
            "stream": [1, 2, 3, 4],
        },
    }
    monkeypatch.setattr(platform_readers, "_get_json", lambda url, timeout: data)
    result = platform_readers.read(
        "https://forum.godotengine.org/t/physics/123", timeout=5
    )
    assert result["ok"] is True
    assert result["replies"] == 2
    assert result["next_url"].endswith("?page=2")
    assert "first" in result["content"]


def test_openreview_returns_abstract_and_reviews(monkeypatch):
    notes = [
        {"invitations": ["/papers/-/Submission"], "content": {
            "title": {"value": "A Paper"}, "abstract": {"value": "abstract text"}}},
        {"invitations": ["/papers/-/Official_Review"], "content": {
            "summary": {"value": "review summary"},
            "weaknesses": {"value": "weak point"}}},
    ]
    monkeypatch.setattr(platform_readers, "_get_json",
                        lambda url, timeout: {"notes": notes})
    result = platform_readers.read(
        "https://openreview.net/forum?id=abc", timeout=5
    )
    assert result["ok"] is True
    assert result["title"] == "A Paper"
    assert result["reviews"] == 1
    assert "review summary" in result["content"]


def test_the_gateway_uses_the_platform_reader(monkeypatch):
    monkeypatch.setattr(
        platform_readers, "read",
        lambda url, timeout: {"ok": True, "kind": "web_page", "url": url,
                              "method": "hn_api", "title": "T", "content": "body"},
    )
    result = GeneralWebGateway().read(
        "https://news.ycombinator.com/item?id=42", timeout=5
    )
    assert result["method"] == "hn_api"


def test_huggingface_model_returns_metadata_card_and_discussions(monkeypatch):
    assert platform_readers.detect(
        "https://huggingface.co/microsoft/phi-2"
    ) == "huggingface"

    def fake_json(url, timeout):
        if url.endswith("/discussions?p=0"):
            return {"count": 147, "discussions": [
                {"num": 12, "title": "Multilingual powerhouse", "numComments": 14},
            ]}
        return {
            "id": "microsoft/phi-2", "pipeline_tag": "text-generation",
            "library_name": "transformers", "downloads": 186898, "likes": 3540,
            "gated": False, "private": False, "lastModified": "2025-12-08",
            "cardData": {"license": "mit"}, "tags": ["transformers"],
            "siblings": [{"rfilename": "a"}, {"rfilename": "b"}],
        }

    monkeypatch.setattr(platform_readers, "_get_json", fake_json)
    monkeypatch.setattr(
        platform_readers, "_get_text",
        lambda url, timeout, max_bytes=30_000: "# Model card\nPhi-2 text",
    )
    result = platform_readers.read("https://huggingface.co/microsoft/phi-2", timeout=5)

    assert result["ok"] is True
    assert result["method"] == "huggingface_api"
    assert "license: mit" in result["content"]
    assert "text-generation" in result["content"]
    assert "147 total" in result["content"]
    assert "Model card" in result["content"]
    assert result["discussions"] == 147


def test_huggingface_dataset_uses_the_dataset_api(monkeypatch):
    seen: list[str] = []

    def fake_json(url, timeout):
        seen.append(url)
        if url.endswith("/discussions?p=0"):
            return {"count": 0, "discussions": []}
        return {"id": "rajpurkar/squad", "cardData": {"license": "cc-by-sa-4.0"},
                "tags": [], "siblings": []}

    monkeypatch.setattr(platform_readers, "_get_json", fake_json)
    monkeypatch.setattr(platform_readers, "_get_text", lambda *a, **k: "")
    result = platform_readers.read(
        "https://huggingface.co/datasets/rajpurkar/squad", timeout=5
    )

    assert result["ok"] is True
    assert any("/api/datasets/rajpurkar/squad" in url for url in seen)
    assert "license: cc-by-sa-4.0" in result["content"]


def test_huggingface_missing_repo_is_empty(monkeypatch):
    def missing(url, timeout):
        raise platform_readers.urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(platform_readers, "_get_json", missing)
    result = platform_readers.read("https://huggingface.co/no/such-model", timeout=5)
    assert result["ok"] is False
    assert result["error_code"] == "platform_empty"


def test_huggingface_non_repo_urls_fall_back():
    result = platform_readers.read("https://huggingface.co/papers/1234", timeout=5)
    assert result["ok"] is False
    assert result["error_code"] == "platform_unsupported"
