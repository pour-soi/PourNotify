from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

SIZES = (16, 20, 24, 32, 48, 64, 128, 256)
ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "pournotify" / "resources" / "pournotify.svg"
OUTPUT = SVG.parent / "icons"
ICO = SVG.parent / "pournotify.ico"


def render_png(size: int) -> bytes:
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        raise RuntimeError(f"Unable to load {SVG}")
    image = QImage(QSize(size, size), QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError(f"Unable to render {size}px icon")
    return bytes(data)


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = []
    payload = []
    for size, data in images:
        dimension = 0 if size == 256 else size
        entries.append(
            struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset)
        )
        payload.append(data)
        offset += len(data)
    return header + b"".join(entries) + b"".join(payload)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    images = []
    for size in SIZES:
        data = render_png(size)
        (OUTPUT / f"pournotify-{size}.png").write_bytes(data)
        images.append((size, data))
    ICO.write_bytes(build_ico(images))


if __name__ == "__main__":
    main()
