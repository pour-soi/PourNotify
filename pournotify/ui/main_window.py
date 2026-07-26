from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, ConfigStore
from ..resources import application_icon
from ..services.delivery import TrayDesktopNotifier
from ..services.dispatcher import NotificationDispatcher
from ..services.history import HistoryStore
from ..services.sounds import SoundManager
from ..services.test_cases import notification_test_cases
from .history import HistoryPage
from .settings import SettingsPage


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, store: ConfigStore):
        super().__init__()
        self.setWindowTitle("PourNotify")
        self.resize(1180, 760)
        self.config, self.store = config, store
        icon = application_icon()
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("PourNotify")
        self.tray.setContextMenu(self._tray_menu())
        self.tray.activated.connect(lambda reason: self.show() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self.history = HistoryStore(limit=config.history_limit)
        self.sounds = SoundManager()
        self.dispatcher = NotificationDispatcher(
            config, self.history, TrayDesktopNotifier(self.tray), self.sounds
        )
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(0)
        self.tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.tabs.addTab(self._dashboard(), "Dashboard")
        self.tabs.addTab(self._test_page(), "Notification Test")
        self.history_page = HistoryPage(self.history)
        self.tabs.addTab(self.history_page, "History")
        self.tabs.addTab(SettingsPage(config, store, self.sounds), "Settings")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)
        self.setStyleSheet("""
            QMainWindow { background: #f5f6f8; }
            QGroupBox, QTableWidget, QTabWidget::pane { background: white; border: 1px solid #dfe3e8;
              border-radius: 8px; margin-top: 8px; }
            QPushButton { background: #24272c; color: white; border: 0; border-radius: 6px;
              padding: 8px 14px; }
            QLineEdit, QComboBox, QSpinBox, QTimeEdit { padding: 6px; border: 1px solid #ccd2d9;
              border-radius: 5px; background: white; }
        """)

    def _dashboard(self) -> QWidget:
        page, layout = QWidget(), QVBoxLayout()
        title = QLabel("PourNotify")
        title.setStyleSheet("font-size: 28px; font-weight: 600;")
        mode = "Demo Mode" if self.config.demo_mode else "Quota source unavailable"
        layout.addWidget(title)
        layout.addWidget(QLabel("Codex Integration\nReady"))
        layout.addWidget(QLabel(f"Bark\n{'Connected' if self.config.bark_enabled else 'Not Configured'}"))
        layout.addWidget(QLabel(f"Quota Provider\n{mode}"))
        layout.addStretch()
        page.setLayout(layout)
        return page

    def _test_page(self) -> QWidget:
        page, layout = QWidget(), QVBoxLayout()
        layout.addWidget(QLabel("Tests use the same notification pipeline as real events."))
        for test_case in notification_test_cases():
            button = QPushButton(test_case.label)
            button.clicked.connect(
                lambda checked=False, value=test_case: self._run_test_case(value)
            )
            layout.addWidget(button)
        layout.addStretch()
        page.setLayout(layout)
        return page

    def _run_test_case(self, test_case) -> None:
        self.dispatcher.dispatch(test_case.notification)
        if test_case.duplicate:
            self.dispatcher.dispatch(test_case.notification)

    def _tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.history_page:
            self.history_page.refresh()

    def _tray_menu(self) -> QMenu:
        menu = QMenu()
        dashboard = QAction("Dashboard", self)
        dashboard.triggered.connect(self.show)
        check = QAction("Check Now", self)
        check.triggered.connect(self.show)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addActions([dashboard, check, quit_action])
        return menu

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
