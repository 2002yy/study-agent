"""§144.13 boundary 2 precondition: bounded fetch-to-file, fail-closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.web.research.visual_image_fetch import (
    REASON_EMPTY,
    REASON_FETCH_FAILED,
    REASON_NOT_A_FETCHER,
    REASON_TOO_LARGE,
    REASON_UNSUPPORTED_TYPE,
    ImageFetchError,
    materialize_image,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 32

_IMAGE_SUFFIXES = {".png", ".jpg", ".gif", ".webp", ".bmp", ".tiff"}


def _written_images(directory: Path) -> list[Path]:
    return [item for item in directory.iterdir() if item.suffix in _IMAGE_SUFFIXES]


def test_materialize_writes_a_content_addressed_file(tmp_path: Path) -> None:
    def fetcher(url: str):
        assert url == "https://x/y.png"
        return _PNG, "image/png"

    fetched = materialize_image(
        "https://x/y.png", fetcher=fetcher, destination_dir=tmp_path
    )

    assert fetched.path.parent == tmp_path
    assert fetched.path.suffix == ".png"
    assert fetched.path.read_bytes() == _PNG
    assert fetched.byte_count == len(_PNG)
    assert fetched.to_dict()["content_type"] == "image/png"


def test_materialize_accepts_a_mapping_payload_and_strips_type_params(
    tmp_path: Path,
) -> None:
    fetched = materialize_image(
        "https://x/y.jpg",
        fetcher=lambda url: {"body": _PNG, "content_type": "image/jpeg; charset=binary"},
        destination_dir=tmp_path,
    )

    assert fetched.content_type == "image/jpeg"
    assert fetched.path.suffix == ".jpg"


def test_materialize_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    fetcher = lambda url: (_PNG, "image/png")  # noqa: E731

    first = materialize_image("https://x/a.png", fetcher=fetcher, destination_dir=tmp_path)
    second = materialize_image("https://x/b.png", fetcher=fetcher, destination_dir=tmp_path)

    assert first.path == second.path


@pytest.mark.parametrize(
    ("fetcher", "reason"),
    [
        (None, REASON_NOT_A_FETCHER),
        (lambda url: (_ for _ in ()).throw(RuntimeError("boom")), REASON_FETCH_FAILED),
        (lambda url: ("not-bytes", "image/png"), REASON_FETCH_FAILED),
        (lambda url: (_PNG, "text/html"), REASON_UNSUPPORTED_TYPE),
        (lambda url: (b"", "image/png"), REASON_EMPTY),
    ],
)
def test_materialize_fails_closed(tmp_path: Path, fetcher, reason: str) -> None:
    with pytest.raises(ImageFetchError) as exc:
        materialize_image("https://x/y", fetcher=fetcher, destination_dir=tmp_path)

    assert exc.value.reason == reason


def test_materialize_rejects_an_oversized_body(tmp_path: Path) -> None:
    big = b"x" * 64

    with pytest.raises(ImageFetchError) as exc:
        materialize_image(
            "https://x/big.png",
            fetcher=lambda url: (big, "image/png"),
            destination_dir=tmp_path,
            max_bytes=16,
        )

    assert exc.value.reason == REASON_TOO_LARGE
    assert _written_images(tmp_path) == []


def test_materialize_never_writes_a_rejected_body(tmp_path: Path) -> None:
    with pytest.raises(ImageFetchError):
        materialize_image(
            "https://x/y", fetcher=lambda url: (_PNG, "application/pdf"), destination_dir=tmp_path
        )

    assert _written_images(tmp_path) == []
