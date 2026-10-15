"""Freeze the real-acceptance fixtures (no model calls, deterministic).

Run once from the repository root:

    python docs/evidence/real-acceptance-2026/build_fixtures.py

Outputs, next to this file:
    screenshot-firefly.png   an uploadable "character panel" screenshot
    reference-notes.pdf      a text-based reference document
    manifest.json            sha256 of every generated fixture

The fixtures are frozen inputs for the real-model acceptance gate.  They are
synthetic and contain no real game data; ground truth lives in scenarios.json.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent

PANEL_LINES = [
    "流萤 · 角色面板",
    "等级 80 / 行迹 10",
    "星魂 1",
    "光锥：记忆中的模样（叠影 1）",
    "攻击力 1234",
    "速度 104",
    "击破特攻 62.5%",
]

PDF_LINES = [
    "Firefly - Reference Notes (synthetic fixture, not real game data)",
    "",
    "1. Super Break damage scales with Break Effect and with the number",
    "   of break instances landed in the same turn.",
    "2. Traces grant +37.3% Break Effect at level 10.",
    "3. Eidolon 2 delays the broken enemy's action by 20%.",
    "4. Light cone superimposition raises the passive multiplier from",
    "   8% (S1) to 16% (S5).",
]

CJK_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in CJK_FONT_CANDIDATES:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def build_screenshot() -> Path:
    width, height = 900, 560
    image = Image.new("RGB", (width, height), (247, 249, 251))
    draw = ImageDraw.Draw(image)
    draw.rectangle([(24, 24), (width - 24, height - 24)], outline=(200, 210, 220), width=2)
    title_font = _font(40)
    body_font = _font(30)
    y = 60
    for index, line in enumerate(PANEL_LINES):
        draw.text((60, y), line, font=title_font if index == 0 else body_font, fill=(30, 40, 50))
        y += 68
    path = HERE / "screenshot-firefly.png"
    image.save(path, format="PNG")
    return path


def _pdf_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_pdf() -> Path:
    """A minimal, valid, text-based PDF (Helvetica) that extractors can read."""

    content = ["BT", "/F1 12 Tf", "72 760 Td", "16 TL"]
    for line in PDF_LINES:
        content.append(f"({_pdf_escape(line)}) Tj T*")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    path = HERE / "reference-notes.pdf"
    path.write_bytes(bytes(out))
    return path


def write_manifest(paths: list[Path]) -> Path:
    manifest = {
        "note": "Frozen inputs for the real-model acceptance gate; synthetic, no real game data.",
        "files": [
            {
                "name": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for path in sorted(paths)
        ],
    }
    target = HERE / "manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> None:
    paths = [build_screenshot(), build_pdf()]
    manifest = write_manifest(paths)
    for path in [*paths, manifest]:
        print(f"{path.relative_to(HERE.parent.parent.parent)}  {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
