from __future__ import annotations

from src.web import bilibili_comments


def test_a_non_bilibili_url_fails_closed():
    result = bilibili_comments.read_comments("https://example.com/video/1")
    assert result["ok"] is False
    assert result["error_code"] == "comments_unsupported"


def test_one_page_of_comments_is_reported_with_scope(monkeypatch):
    def fake(url, timeout):
        if "web-interface/view" in url:
            return {"data": {"aid": 123, "title": "T"}}
        return {"data": {
            "page": {"count": 57},
            "replies": [
                {"member": {"uname": "甲"}, "ctime": 1700000000,
                 "content": {"message": "第一条"}, "like": 3, "rcount": 1},
                {"member": {"uname": "乙"}, "ctime": 1700000100,
                 "content": {"message": "第二条"}, "like": 0, "rcount": 0},
            ],
        }}

    monkeypatch.setattr(bilibili_comments, "_get_json", fake)
    result = bilibili_comments.read_comments(
        "https://www.bilibili.com/video/BV1oV4y187A1", page=2, limit=5
    )
    assert result["ok"] is True
    assert result["page"] == 2
    assert result["read"] == 2
    assert result["total"] == 57
    assert result["may_be_partial"] is True
    assert [item["author"] for item in result["comments"]] == ["甲", "乙"]
    assert result["comments"][0]["likes"] == 3


def test_an_empty_page_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(
        bilibili_comments, "_get_json",
        lambda url, timeout: {"data": {"aid": 1, "title": "T", "page": {"count": 0},
                                       "replies": []}},
    )
    result = bilibili_comments.read_comments(
        "https://www.bilibili.com/video/BV1oV4y187A1"
    )
    assert result["ok"] is False
    assert result["error_code"] == "comments_empty"
