from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QFrame, QPushButton

from pournotify.config import AppConfig, ConfigStore
from pournotify.models import Category
from pournotify.services.history import HistoryStore
from pournotify.ui.main_window import MainWindow


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

    assert page.table.rowCount() == len(Category) == 13
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
        if button.property("test_case") == "Codex Task Completed"
    )
    test_button.click()
    assert len(dispatched) == 1
    assert dispatched[0].category == Category.TASK_COMPLETED
    dispose(window)
