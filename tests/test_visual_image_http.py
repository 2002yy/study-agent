"""§144.16 safety contract for the real web-image fetcher."""

from __future__ import annotations

from urllib.error import HTTPError, URLError

import pytest

from src.web.research.visual_image_fetch import ImageFetchError
from src.web.research.visual_image_http import (
    REASON_ENCODING_UNSUPPORTED,
    REASON_FETCH_FAILED,
    REASON_HTTP_STATUS,
    REASON_NOT_PUBLIC,
    REASON_REDIRECT_NOT_PUBLIC,
    REASON_TIMEOUT,
    REASON_TOO_MANY_REDIRECTS,
    REASON_TOO_LARGE,
    REASON_UNSUPPORTED_TYPE,
    USER_AGENT,
    fetch_image,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 32
_PUBLIC = "https://cdn.example.com/pic.png"


class _FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200, headers: dict | None = None):
        self._body = body
        self._pos = 0
        self.status = status
        self.headers = headers or {}
        self.read_calls: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_calls.append(size)
        if size is None or size < 0:
            size = len(self._body) - self._pos
        chunk = self._body[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _image_headers(**overrides: str) -> dict:
    headers = {"Content-Type": "image/png", "Content-Encoding": "identity"}
    headers.update(overrides)
    return headers


def _opener(response: _FakeResponse, seen: list | None = None):
    def open_url(request, timeout=None):
        if seen is not None:
            seen.append(request)
        return response

    return open_url


def _redirect_opener(chain: dict[str, object], seen: list | None = None):
    def open_url(request, timeout=None):
        if seen is not None:
            seen.append(request)
        target = chain[request.full_url]
        if isinstance(target, Exception):
            raise target
        return target

    return open_url


def test_fetch_returns_bytes_and_sends_no_credentials() -> None:
    seen: list = []
    response = _FakeResponse(_PNG, headers=_image_headers())

    body, content_type = fetch_image(
        _PUBLIC, opener=_opener(response, seen), max_bytes=1024
    )

    assert body == _PNG
    assert content_type == "image/png"
    assert len(seen) == 1
    headers = {k.lower(): v for k, v in seen[0].header_items()}
    assert headers.get("user-agent") == USER_AGENT
    assert "cookie" not in headers
    assert "authorization" not in headers


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/pic.png",
        "http://localhost/pic.png",
        "http://10.0.0.5/pic.png",
        "file:///etc/passwd",
        # Credentials in the URL must be refused. Assembled at runtime so the
        # secret scanner does not read the literal as a Basic Auth credential.
        "https://" + "user" + ":" + "pass" + "@cdn.example.com/pic.png",
    ],
)
def test_fetch_refuses_a_non_public_initial_url(url: str) -> None:
    calls: list = []

    with pytest.raises(ImageFetchError) as exc:
        fetch_image(url, opener=lambda *a, **k: calls.append(1))

    assert exc.value.reason == REASON_NOT_PUBLIC
    assert calls == []


def test_fetch_re_validates_every_redirect_hop() -> None:
    # A public URL that redirects to a private address must be refused: the hop
    # is re-checked, not trusted because the first URL was public.
    redirect = HTTPError(_PUBLIC, 302, "Found", {"Location": "http://127.0.0.1/x.png"}, None)

    with pytest.raises(ImageFetchError) as exc:
        fetch_image(
            _PUBLIC,
            opener=_redirect_opener({_PUBLIC: redirect}),
        )

    assert exc.value.reason == REASON_REDIRECT_NOT_PUBLIC


def test_fetch_follows_a_public_redirect() -> None:
    seen: list = []
    hop2 = "https://cdn2.example.com/pic.png"
    redirect = HTTPError(_PUBLIC, 302, "Found", {"Location": hop2}, None)
    opener = _redirect_opener(
        {_PUBLIC: redirect, hop2: _FakeResponse(_PNG, headers=_image_headers())}, seen
    )

    body, _ = fetch_image(_PUBLIC, opener=opener, max_bytes=1024)

    assert body == _PNG
    assert [request.full_url for request in seen] == [_PUBLIC, hop2]


def test_fetch_caps_the_redirect_chain() -> None:
    redirect = HTTPError(_PUBLIC, 302, "Found", {"Location": _PUBLIC + "?again"}, None)

    with pytest.raises(ImageFetchError) as exc:
        fetch_image(
            _PUBLIC,
            opener=_redirect_opener({_PUBLIC: redirect, _PUBLIC + "?again": redirect}),
            max_redirects=1,
        )

    assert exc.value.reason == REASON_TOO_MANY_REDIRECTS


def test_fetch_requires_an_allowed_image_content_type() -> None:
    response = _FakeResponse(b"<html>", headers={"Content-Type": "text/html"})

    with pytest.raises(ImageFetchError) as exc:
        fetch_image(_PUBLIC, opener=_opener(response), max_bytes=1024)

    assert exc.value.reason == REASON_UNSUPPORTED_TYPE


def test_fetch_refuses_a_non_identity_content_encoding() -> None:
    response = _FakeResponse(_PNG, headers=_image_headers(**{"Content-Encoding": "gzip"}))

    with pytest.raises(ImageFetchError) as exc:
        fetch_image(_PUBLIC, opener=_opener(response), max_bytes=1024)

    assert exc.value.reason == REASON_ENCODING_UNSUPPORTED


def test_fetch_rejects_an_oversized_content_length_before_reading() -> None:
    response = _FakeResponse(_PNG, headers=_image_headers(**{"Content-Length": "999999"}))

    with pytest.raises(ImageFetchError) as exc:
        fetch_image(_PUBLIC, opener=_opener(response), max_bytes=64)

    assert exc.value.reason == REASON_TOO_LARGE
    assert response.read_calls == []


def test_fetch_enforces_the_cap_without_trusting_content_length() -> None:
    # No Content-Length at all, and the body is larger than the cap: the streamed
    # read must still stop with a hard bound.
    response = _FakeResponse(b"x" * 5000, headers=_image_headers())

    with pytest.raises(ImageFetchError) as exc:
        fetch_image(_PUBLIC, opener=_opener(response), max_bytes=256)

    assert exc.value.reason == REASON_TOO_LARGE
    assert len(response.read_calls) >= 1


def test_fetch_normalizes_timeout_and_network_failures() -> None:
    def timeout_opener(request, timeout=None):
        raise TimeoutError("slow")

    def network_opener(request, timeout=None):
        raise URLError("dns")

    with pytest.raises(ImageFetchError) as timeout_exc:
        fetch_image(_PUBLIC, opener=timeout_opener)
    assert timeout_exc.value.reason == REASON_TIMEOUT

    with pytest.raises(ImageFetchError) as net_exc:
        fetch_image(_PUBLIC, opener=network_opener)
    assert net_exc.value.reason == REASON_FETCH_FAILED


def test_fetch_normalizes_an_error_status() -> None:
    error = HTTPError(_PUBLIC, 500, "Server Error", {}, None)

    with pytest.raises(ImageFetchError) as exc:
        fetch_image(_PUBLIC, opener=_redirect_opener({_PUBLIC: error}))

    assert exc.value.reason == REASON_HTTP_STATUS


def test_fetch_rejects_an_empty_body() -> None:
    response = _FakeResponse(b"", headers=_image_headers())

    with pytest.raises(ImageFetchError) as exc:
        fetch_image(_PUBLIC, opener=_opener(response), max_bytes=1024)

    assert exc.value.reason == "image_body_empty"
