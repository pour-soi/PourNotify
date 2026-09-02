from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton

from pournotify.config import AppConfig, ConfigStore
from pournotify.models import Category
from pournotify.services.history import HistoryStore
from pournotify.ui.main_window import MainWindow
from pournotify.ui.settings import SettingsPage, codex_local_fallback_supported


def app():
    return QApplication.instance() or QApplication([])


def make_window(tmp_path, monkeypatch):
    app()
    store = ConfigStore(tmp_path / "config.json")
    config = AppConfig()
    store.save(config)
    monkeypatch.setattr(
        "pournotify.ui.main_window.HistoryStore",
        lambda limit: HistoryStore(tmp_path / "history.json", limit),
    )
    return MainWindow(config, store), config, store


def dispose(window):
    window.tray.hide()
    window.hide()
    window.deleteLater()
    QApplication.processEvents()


def test_sidebar_navigation_and_page_contract(tmp_path, monkeypatch):
    window, _, _ = make_window(tmp_path, monkeypatch)

    assert window.size().width() == 1180
    assert window.size().height() == 760
    assert window.centralWidget().objectName() == "appShell"
    sidebar = window.centralWidget().findChild(QFrame, "sidebar")
    assert sidebar.width() == 208
    assert [button.text() for button in window.nav_buttons] == [
        "Dashboard",
        "Notification Test",
        "History",
        "Settings",
    ]
    assert window.stack.count() == 4
    window.navigate(2)
    assert window.stack.currentIndex() == 2
    assert window.nav_buttons[2].isChecked()
    dispose(window)


def test_category_editor_preserves_every_category_and_setting(tmp_path, monkeypatch):
    window, config, _ = make_window(tmp_path, monkeypatch)
    page = window.settings_page

    assert page.attention_table.rowCount() == 3
    assert page.table.rowCount() == len(Category) - 3 == 11
    assert page.attention_table.columnCount() == 5
    assert page.table.columnCount() == 5
    assert set(page.category_controls) == set(Category)
    assert set(next(iter(page.category_controls.values()))) == {
        "enabled",
        "bark",
        "desktop",
        "history",
        "sound",
        "choice",
        "volume",
        "priority",
    }
    for category, controls in page.category_controls.items():
        setting = config.categories[category.value]
        assert controls["enabled"].isChecked() == setting.enabled
        assert controls["bark"].isChecked() == setting.bark
        assert controls["desktop"].isChecked() == setting.desktop
        assert controls["history"].isChecked() == setting.history
        assert controls["sound"].isChecked() == setting.sound
        assert controls["choice"].currentText() == setting.sound_name
        assert controls["volume"].value() == setting.volume
        assert controls["priority"].currentText().lower() == setting.priority.value
    dispose(window)


def test_theme_modes_and_diagnostics_utility(tmp_path, monkeypatch):
    window, config, _ = make_window(tmp_path, monkeypatch)
    opened: list[QUrl] = []
    monkeypatch.setattr(
        "pournotify.ui.main_window.diagnostics_log_path",
        lambda: tmp_path / "logs" / "notify-diagnostics.jsonl",
    )
    monkeypatch.setattr(
        "pournotify.ui.main_window.QDesktopServices.openUrl",
        lambda url: opened.append(url) or True,
    )

    for mode in ("system", "light", "dark"):
        window.apply_theme(mode)
        assert config.theme == mode
        assert QApplication.instance().styleSheet()

    diagnostics = next(
        button
        for button in window.findChildren(QPushButton)
        if button.property("utility") == "diagnostics"
    )
    diagnostics.click()
    assert opened == [QUrl.fromLocalFile(str(tmp_path / "logs"))]
    dispose(window)


def test_notification_test_still_uses_main_dispatcher(tmp_path, monkeypatch):
    window, _, _ = make_window(tmp_path, monkeypatch)
    dispatched = []

    class Recorder:
        def dispatch(self, notification):
            dispatched.append(notification)

    window.dispatcher = Recorder()
    test_button = next(
        button
        for button in window.findChildren(QPushButton)
        if button.property("test_case") == "Codex Needs Attention: Finished"
    )
    test_button.click()
    assert len(dispatched) == 1
    assert dispatched[0].category == Category.TASK_COMPLETED
    dispose(window)


def test_windows_startup_setting_updates_config_and_registration(tmp_path, monkeypatch):
    registrations = []
    monkeypatch.setattr("pournotify.ui.settings.startup_supported", lambda: True)
    monkeypatch.setattr("pournotify.ui.settings.legacy_startup_entries", list)
    monkeypatch.setattr(
        "pournotify.ui.settings.set_startup_enabled", registrations.append
    )
    monkeypatch.setattr(
        "pournotify.ui.settings.migrate_legacy_startup_entries", list
    )
    monkeypatch.setattr(
        "pournotify.ui.settings.QMessageBox.information", lambda *args: None
    )
    window, config, store = make_window(tmp_path, monkeypatch)
    page = window.settings_page

    assert page.start_with_windows.isEnabled()
    assert not page.start_with_windows.isChecked()
    page.start_with_windows.setChecked(True)
    page.save()

    assert registrations == [True]
    assert config.start_with_windows is True
    assert store.load().start_with_windows is True
    dispose(window)


def test_local_fallback_setting_is_opt_in_and_notifies_only_on_change(tmp_path, monkeypatch):
    app()
    changes = []
    store = ConfigStore(tmp_path / "config.json")
    config = AppConfig()
    store.save(config)
    monkeypatch.setattr("pournotify.ui.settings.startup_supported", lambda: False)
    monkeypatch.setattr("pournotify.ui.settings.legacy_startup_entries", list)
    monkeypatch.setattr(
        "pournotify.ui.settings.codex_local_fallback_supported", lambda: True
    )
    monkeypatch.setattr(
        "pournotify.ui.settings.QMessageBox.information", lambda *args: None
    )
    page = SettingsPage(config, store, object(), fallback_changed=changes.append)

    assert page.codex_local_fallback.text() == (
        "Recover missed Codex attention events with the local observer"
    )
    assert any(
        "user-facing Codex task can need attention" in label.text()
        for label in page.findChildren(QLabel)
    )
    assert page.codex_local_fallback.isEnabled()
    assert not page.codex_local_fallback.isChecked()

    page.save()
    assert changes == []

    page.codex_local_fallback.setChecked(True)
    page.save()
    page.save()

    assert changes == [True]
    assert store.load().codex_local_fallback_enabled is True

    page.codex_local_fallback.setChecked(False)
    page.save()
    assert changes == [True, False]
    page.deleteLater()
    QApplication.processEvents()


def test_local_fallback_platform_support_matches_windows():
    import sys

    assert codex_local_fallback_supported() is (sys.platform == "win32")


def test_local_fallback_setting_is_disabled_and_preserved_off_windows(tmp_path, monkeypatch):
    app()
    changes = []
    store = ConfigStore(tmp_path / "config.json")
    config = AppConfig(codex_local_fallback_enabled=True)
    store.save(config)
    monkeypatch.setattr("pournotify.ui.settings.startup_supported", lambda: False)
    monkeypatch.setattr("pournotify.ui.settings.legacy_startup_entries", list)
    monkeypatch.setattr(
        "pournotify.ui.settings.codex_local_fallback_supported", lambda: False
    )
    monkeypatch.setattr(
        "pournotify.ui.settings.QMessageBox.information", lambda *args: None
    )
    page = SettingsPage(config, store, object(), fallback_changed=changes.append)

    assert not page.codex_local_fallback.isEnabled()
    assert page.codex_local_fallback.toolTip() == (
        "Local fallback detection is available on Windows."
    )
    page.codex_local_fallback.setChecked(False)
    page.save()

    assert store.load().codex_local_fallback_enabled is True
    assert changes == []
    page.deleteLater()
    QApplication.processEvents()
