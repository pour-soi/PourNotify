import shutil
import sys

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from pournotify.resources import application_icon, resource_path


def test_application_icon_is_resolvable_and_non_null():
    assert resource_path("pournotify.svg").is_file()
    app = QApplication.instance() or QApplication([])
    assert app is not None
    tray = QSystemTrayIcon(application_icon())
    assert not tray.icon().isNull()


def test_application_icon_resolves_from_frozen_bundle(monkeypatch, tmp_path):
    bundled = tmp_path / "pournotify" / "resources"
    bundled.mkdir(parents=True)
    shutil.copyfile(resource_path("pournotify.svg"), bundled / "pournotify.svg")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert resource_path("pournotify.svg") == bundled / "pournotify.svg"
    assert not application_icon().isNull()
