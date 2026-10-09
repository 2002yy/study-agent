from __future__ import annotations

from urllib.error import HTTPError

import pytest

from tools import qualify_anonymous_platforms as doctor


@pytest.mark.parametrize("payload,status", [(b'[{"id": 1}]', "public_feed_observed"),
                                          (b'{"message": "blocked"}', "invalid_response")])
def test_public_probe_does_not_qualify_from_http_success(monkeypatch, payload, status):
    class Response:
        status = 200
        url = "https://www.v2ex.com/api/topics/hot.json"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            assert limit == doctor.MAX_BYTES + 1
            return payload

    def open_public(request, timeout):
        assert timeout == 8
        assert not request.has_header("Cookie")
        return Response()

    monkeypatch.setattr(doctor, "urlopen", open_public)
    row = doctor.probe("v2ex", "feed", Response.url)
    assert row["status"] == status
    assert row["qualified"] is False
    assert row["payload_sha256"]


def test_blocked_platform_is_unavailable_not_empty(monkeypatch):
    def reject(*args, **kwargs):
        raise HTTPError("https://www.bilibili.com", 412, "blocked", {}, None)

    monkeypatch.setattr(doctor, "urlopen", reject)
    row = doctor.probe("bilibili", "search", "https://www.bilibili.com")
    assert row["status"] == "unavailable"
    assert row["reason"] == "http_412"
    assert row["qualified"] is False
