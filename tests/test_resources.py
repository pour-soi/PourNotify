import shutil
import struct
import sys

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from pournotify.resources import application_icon, resource_path


def test_application_icon_is_resolvable_and_non_null():
    assert resource_path("pournotify.svg").is_file()
    assert resource_path("pournotify-source.jpg").is_file()
    assert resource_path("icons/pournotify-256.png").is_file()
    app = QApplication.instance() or QApplication([])
    assert app is not None
    tray = QSystemTrayIcon(application_icon())
    assert not tray.icon().isNull()


def test_application_icon_resolves_from_frozen_bundle(monkeypatch, tmp_path):
    bundled = tmp_path / "pournotify" / "resources" / "icons"
    bundled.mkdir(parents=True)
    shutil.copyfile(
        resource_path("icons/pournotify-256.png"), bundled / "pournotify-256.png"
    )
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert resource_path("icons/pournotify-256.png") == bundled / "pournotify-256.png"
    assert not application_icon().isNull()


def test_generated_icon_assets_cover_required_sizes():
    expected = {16, 20, 24, 32, 48, 64, 128, 256}
    icon_dir = resource_path("icons")
    for size in expected:
        image = QImage(str(icon_dir / f"pournotify-{size}.png"))
        assert not image.isNull()
        assert image.width() == image.height() == size
        assert image.hasAlphaChannel()

    data = resource_path("pournotify.ico").read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data)
    assert (reserved, kind, count) == (0, 1, len(expected))
    embedded = set()
    for index in range(count):
        width, height = struct.unpack_from("<BB", data, 6 + index * 16)
        embedded.add(256 if width == height == 0 else width)
    assert embedded == expected
