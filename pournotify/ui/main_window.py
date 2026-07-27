from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, ConfigStore
from ..resources import application_icon
from ..services.delivery import TrayDesktopNotifier
from ..services.diagnostics import diagnostics_log_path
from ..services.dispatcher import NotificationDispatcher
from ..services.history import HistoryStore
from ..services.sounds import SoundManager
from ..services.test_cases import NotificationTestCase, notification_test_cases
from .history import HistoryPage
from .settings import SettingsPage
from .theme import stylesheet_for


class MainWindow(QMainWindow):
    PAGE_TITLES = (
        ("Dashboard", "Notification delivery at a glance."),
        ("Notification Test", "Exercise the same dispatcher used by real notifications."),
        ("History", "Review, search, copy, and export notification records."),
        ("Settings", "Configure delivery channels, quiet hours, and categories."),
    )

    def __init__(self, config: AppConfig, store: ConfigStore):
        super().__init__()
        self.setWindowTitle("PourNotify")
        self.resize(1180, 760)
        self.setMinimumSize(920, 620)
        self.config, self.store = config, store
        icon = application_icon()
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("PourNotify")
        self.tray.setContextMenu(self._tray_menu())
        self.tray.activated.connect(
            lambda reason: self.show() if reason == QSystemTrayIcon.Trigger else None
        )
        self.tray.show()
        self.history = HistoryStore(limit=config.history_limit)
        self.sounds = SoundManager()
        self.dispatcher = NotificationDispatcher(
            config, self.history, TrayDesktopNotifier(self.tray), self.sounds
        )

        self.stack = QStackedWidget()
        self.stack.addWidget(self._wrap_page(0, self._dashboard()))
        self.stack.addWidget(self._wrap_page(1, self._test_page()))
        self.history_page = HistoryPage(self.history)
        self.stack.addWidget(self._wrap_page(2, self.history_page))
        self.settings_page = SettingsPage(
            config, store, self.sounds, theme_changed=self.apply_theme
        )
        self.stack.addWidget(self._wrap_page(3, self.settings_page))
        self.stack.currentChanged.connect(self._page_changed)

        shell = QWidget()
        shell.setObjectName("appShell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self._sidebar(icon))
        shell_layout.addWidget(self.stack, 1)
        self.setCentralWidget(shell)
        self._setup_menu_bar()
        self.apply_theme(config.theme)
        QApplication.styleHints().colorSchemeChanged.connect(self._system_theme_changed)

    def _sidebar(self, icon) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(208)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(8)

        brand = QHBoxLayout()
        brand.setSpacing(12)
        brand_icon = QLabel()
        brand_icon.setPixmap(icon.pixmap(36, 36))
        brand_icon.setFixedSize(36, 36)
        brand.addWidget(brand_icon)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        title = QLabel("PourNotify")
        title.setObjectName("brandTitle")
        subtitle = QLabel("LOCAL NOTIFICATIONS")
        subtitle.setObjectName("brandSubtitle")
        brand_text.addWidget(title)
        brand_text.addWidget(subtitle)
        brand.addLayout(brand_text, 1)
        layout.addLayout(brand)
        layout.addSpacing(20)

        self.navigation = QButtonGroup(self)
        self.navigation.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        for index, label in enumerate(("Dashboard", "Notification Test", "History", "Settings")):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda checked=False, value=index: self.navigate(value))
            self.navigation.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)
        self.nav_buttons[0].setChecked(True)

        layout.addStretch()
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        layout.addWidget(divider)
        diagnostics = self._utility_button(
            "Open Diagnostics", self._open_notification_diagnostics
        )
        diagnostics.setObjectName("utilityButton")
        diagnostics.setProperty("utility", "diagnostics")
        layout.addWidget(diagnostics)
        self.help_button = self._utility_button("Help", self._show_help_menu)
        layout.addWidget(self.help_button)
        return sidebar

    @staticmethod
    def _utility_button(label: str, action: Callable[[], None]) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("utilityButton")
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(action)
        return button

    def _wrap_page(self, index: int, content: QWidget) -> QWidget:
        title_text, subtitle_text = self.PAGE_TITLES[index]
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(16)
        title = QLabel(title_text)
        title.setObjectName("pageTitle")
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(4)
        layout.addWidget(content, 1)
        return page

    def _dashboard(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        grid = QGridLayout()
        grid.setSpacing(16)
        grid.addWidget(self._status_card("Codex Integration", "Ready", "success"), 0, 0)
        bark_state = "Connected" if self.config.bark_enabled else "Not configured"
        grid.addWidget(
            self._status_card(
                "Bark", bark_state, "success" if self.config.bark_enabled else "warning"
            ),
            0,
            1,
        )
        grid.addWidget(self._status_card("Desktop", "Ready", "success"), 1, 0)
        grid.addWidget(self._status_card("History", "Available", "success"), 1, 1)
        grid.addWidget(self._status_card("Diagnostics", "Logging enabled", "success"), 2, 0)
        quota = "Demo mode" if self.config.demo_mode else "Provider unavailable"
        grid.addWidget(self._status_card("Quota Provider", quota, "neutral"), 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch()
        return content

    @staticmethod
    def _status_card(label: str, status: str, state: str) -> QWidget:
        card = QFrame()
        card.setObjectName("statusCard")
        card.setMinimumHeight(100)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        heading = QLabel(label)
        heading.setObjectName("sectionTitle")
        badge = QLabel(status)
        badge.setObjectName("statusBadge")
        badge.setProperty("state", state)
        badge.setAlignment(Qt.AlignCenter)
        badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(heading)
        layout.addWidget(badge)
        return card

    def _test_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 24)
        layout.setSpacing(12)
        for test_case in notification_test_cases():
            layout.addWidget(self._test_case_card(test_case))
        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _test_case_card(self, test_case: NotificationTestCase) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(3)
        title = QLabel(test_case.label)
        title.setObjectName("sectionTitle")
        category = QLabel(test_case.notification.category.value.replace("_", " ").title())
        category.setObjectName("metadata")
        text.addWidget(title)
        text.addWidget(category)
        layout.addLayout(text, 1)
        button = QPushButton("Run Test")
        button.setProperty("test_case", test_case.label)
        button.clicked.connect(lambda checked=False, value=test_case: self._run_test_case(value))
        layout.addWidget(button)
        return card

    def navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)

    def _run_test_case(self, test_case: NotificationTestCase) -> None:
        self.dispatcher.dispatch(test_case.notification)
        if test_case.duplicate:
            self.dispatcher.dispatch(test_case.notification)

    def _page_changed(self, index: int) -> None:
        if index == 2:
            self.history_page.refresh()

    def apply_theme(self, mode: str) -> None:
        self.config.theme = mode if mode in {"system", "light", "dark"} else "system"
        QApplication.instance().setStyleSheet(stylesheet_for(self.config.theme))

    def _system_theme_changed(self) -> None:
        if self.config.theme == "system":
            self.apply_theme("system")

    def _tray_menu(self) -> QMenu:
        menu = QMenu()
        dashboard = QAction("Dashboard", self)
        dashboard.triggered.connect(lambda: (self.navigate(0), self.show()))
        check = QAction("Check Now", self)
        check.triggered.connect(self.show)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addActions([dashboard, check, quit_action])
        return menu

    def _setup_menu_bar(self) -> None:
        self.help_menu = self.menuBar().addMenu("Help")
        diagnostics = QAction("Open Notification Diagnostics", self)
        diagnostics.triggered.connect(self._open_notification_diagnostics)
        self.help_menu.addAction(diagnostics)

    def _show_help_menu(self) -> None:
        self.help_menu.exec(
            self.help_button.mapToGlobal(self.help_button.rect().topRight())
        )

    @staticmethod
    def _open_notification_diagnostics() -> None:
        folder = diagnostics_log_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
