from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, ConfigStore
from ..models import CATEGORY_LABELS, Category, Priority
from ..services.sounds import BUILT_IN_SOUNDS, SoundManager
from ..services.startup import (
    legacy_startup_entries,
    migrate_legacy_startup_entries,
    set_startup_enabled,
    startup_supported,
)


def codex_local_fallback_supported() -> bool:
    return sys.platform == "win32"


CODEX_ATTENTION_CATEGORIES = (
    Category.TASK_COMPLETED,
    Category.INPUT_REQUIRED,
    Category.APPROVAL_REQUIRED,
)


class SettingsPage(QWidget):
    def __init__(
        self,
        config: AppConfig,
        store: ConfigStore,
        sounds: SoundManager,
        theme_changed: Callable[[str], None] | None = None,
        fallback_changed: Callable[[bool], None] | None = None,
    ):
        super().__init__()
        self.config, self.store, self.sounds = config, store, sounds
        self.theme_changed = theme_changed
        self.fallback_changed = fallback_changed
        self.category_controls: dict[Category, dict[str, object]] = {}
        self.preview_category = Category.TASK_COMPLETED

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 24)
        layout.setSpacing(16)
        layout.addWidget(self._appearance_card())
        layout.addWidget(self._startup_card())
        layout.addWidget(self._codex_attention_card())
        layout.addWidget(self._bark_card())
        layout.addWidget(self._quiet_card())
        layout.addWidget(self._anti_spam_card())
        layout.addWidget(self._categories_card())
        layout.addLayout(self._actions())
        scroll.setWidget(content)
        outer.addWidget(scroll)

    @staticmethod
    def _card(title: str, description: str = "") -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        if description:
            copy = QLabel(description)
            copy.setObjectName("sectionDescription")
            copy.setWordWrap(True)
            layout.addWidget(copy)
        return card, layout

    def _appearance_card(self) -> QWidget:
        card, layout = self._card(
            "Appearance", "Use the system appearance or choose a consistent light or dark theme."
        )
        row = QHBoxLayout()
        row.setSpacing(8)
        self.appearance_group = QButtonGroup(self)
        self.appearance_group.setExclusive(True)
        self.appearance_buttons: dict[str, QPushButton] = {}
        for mode in ("system", "light", "dark"):
            button = QPushButton(mode.title())
            button.setObjectName("appearanceButton")
            button.setCheckable(True)
            button.setChecked(self.config.theme == mode)
            button.clicked.connect(
                lambda checked=False, value=mode: self._preview_theme(value)
            )
            self.appearance_group.addButton(button)
            self.appearance_buttons[mode] = button
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        return card

    def _preview_theme(self, mode: str) -> None:
        if self.theme_changed is not None:
            self.theme_changed(mode)

    def _startup_card(self) -> QWidget:
        card, layout = self._card(
            "Windows Startup",
            "Keep PourNotify resident after sign-in without opening the main window.",
        )
        self.start_with_windows = QCheckBox(
            "Start PourNotify automatically when I sign in"
        )
        self.start_with_windows.setChecked(
            self.config.start_with_windows or bool(legacy_startup_entries())
        )
        self.start_with_windows.setEnabled(startup_supported())
        layout.addWidget(self.start_with_windows)
        return card

    def _codex_attention_card(self) -> QWidget:
        card, layout = self._card(
            "Notify me when Codex needs my attention",
            "Finished and Input Required are supported. Approval Required is retained for "
            "compatibility and defaults to off; real permission-wait detection is not supported "
            "reliably. Each category keeps its existing delivery settings.",
        )
        self.attention_table = self._category_table(
            CODEX_ATTENTION_CATEGORIES,
            object_name="codexAttentionTable",
            minimum_height=184,
        )
        layout.addWidget(self.attention_table)
        self.codex_local_fallback = QCheckBox(
            "Recover missed Codex attention events with the local observer"
        )
        self.codex_local_fallback.setChecked(self.config.codex_local_fallback_enabled)
        self.codex_local_fallback_available = codex_local_fallback_supported()
        self.codex_local_fallback.setEnabled(self.codex_local_fallback_available)
        if not self.codex_local_fallback_available:
            self.codex_local_fallback.setToolTip("Local fallback detection is available on Windows.")
        layout.addWidget(self.codex_local_fallback)
        return card

    def _bark_card(self) -> QWidget:
        card, layout = self._card(
            "Bark", "Send selected notification categories to the configured Bark server."
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self.bark_enabled = QCheckBox("Enable Bark")
        self.bark_enabled.setChecked(self.config.bark_enabled)
        self.bark_url = QLineEdit(self.config.bark_server_url)
        self.bark_key = QLineEdit(self.config.bark_device_key)
        self.bark_key.setEchoMode(QLineEdit.Password)
        grid.addWidget(self.bark_enabled, 0, 0, 1, 2)
        grid.addWidget(self._field_label("HTTPS SERVER"), 1, 0)
        grid.addWidget(self.bark_url, 1, 1)
        grid.addWidget(self._field_label("DEVICE KEY"), 2, 0)
        grid.addWidget(self.bark_key, 2, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return card

    def _quiet_card(self) -> QWidget:
        card, layout = self._card(
            "Quiet Hours", "Reduce interruption while preserving configured critical alerts."
        )
        grid = QGridLayout()
        grid.setSpacing(10)
        self.quiet_enabled = QCheckBox("Enable quiet hours")
        self.quiet_enabled.setChecked(self.config.quiet_hours_enabled)
        self.quiet_start, self.quiet_end = QTimeEdit(), QTimeEdit()
        self.quiet_start.setTime(
            self.quiet_start.time().fromString(self.config.quiet_start, "HH:mm")
        )
        self.quiet_end.setTime(
            self.quiet_end.time().fromString(self.config.quiet_end, "HH:mm")
        )
        self.bark_silent = QCheckBox("Make Bark silent")
        self.bark_silent.setChecked(self.config.quiet_bark_silent)
        self.critical_bypass = QCheckBox("Critical notifications may bypass")
        self.critical_bypass.setChecked(self.config.quiet_allow_critical)
        grid.addWidget(self.quiet_enabled, 0, 0, 1, 4)
        grid.addWidget(self._field_label("FROM"), 1, 0)
        grid.addWidget(self.quiet_start, 1, 1)
        grid.addWidget(self._field_label("TO"), 1, 2)
        grid.addWidget(self.quiet_end, 1, 3)
        grid.addWidget(self.bark_silent, 2, 0, 1, 2)
        grid.addWidget(self.critical_bypass, 2, 2, 1, 2)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)
        return card

    def _anti_spam_card(self) -> QWidget:
        card, layout = self._card(
            "Anti-spam", "Control duplicate handling and notification rate limits."
        )
        grid = QGridLayout()
        grid.setSpacing(10)
        self.suppress = QCheckBox("Suppress duplicates")
        self.suppress.setChecked(self.config.duplicate_suppression)
        self.merge = QCheckBox("Merge duplicates")
        self.merge.setChecked(self.config.merge_duplicates)
        self.cooldown = QSpinBox()
        self.cooldown.setRange(0, 86400)
        self.cooldown.setValue(self.config.cooldown_seconds)
        self.rate = QSpinBox()
        self.rate.setRange(1, 120)
        self.rate.setValue(self.config.max_per_minute)
        grid.addWidget(self.merge, 0, 0)
        grid.addWidget(self.suppress, 0, 1)
        grid.addWidget(self._field_label("COOLDOWN SECONDS"), 1, 0)
        grid.addWidget(self.cooldown, 1, 1)
        grid.addWidget(self._field_label("MAXIMUM PER MINUTE"), 1, 2)
        grid.addWidget(self.rate, 1, 3)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)
        return card

    def _categories_card(self) -> QWidget:
        card, layout = self._card(
            "Other Notification Categories",
            "Unrelated system and quota events keep independent delivery settings.",
        )
        other_categories = tuple(
            category for category in Category if category not in CODEX_ATTENTION_CATEGORIES
        )
        self.table = self._category_table(
            other_categories,
            object_name="categoryTable",
            minimum_height=520,
        )
        layout.addWidget(self.table)
        return card

    def _category_table(
        self,
        categories: tuple[Category, ...],
        *,
        object_name: str,
        minimum_height: int,
    ) -> QTableWidget:
        table = QTableWidget(len(categories), 5)
        table.setObjectName(object_name)
        table.setAlternatingRowColors(True)
        table.setMinimumHeight(minimum_height)
        table.setHorizontalHeaderLabels(
            ["Category", "Enabled", "Delivery Channels", "Sound", "Priority"]
        )
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setShowGrid(False)
        for row, category in enumerate(categories):
            self._populate_category_row(table, row, category)
            table.setRowHeight(row, 46)
        table.currentCellChanged.connect(
            lambda row, _column, _previous_row, _previous_column, values=categories: (
                self._set_preview_category(values[row]) if row >= 0 else None
            )
        )
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        return table

    def _populate_category_row(
        self, table: QTableWidget, row: int, category: Category
    ) -> None:
        setting = self.config.categories[category.value]
        label = QTableWidgetItem(CATEGORY_LABELS[category])
        if category == Category.APPROVAL_REQUIRED:
            label.setText("Approval Required (unsupported)")
            label.setToolTip("Compatibility only; real approval-wait detection is not reliable.")
        label.setData(Qt.UserRole, category.value)
        table.setItem(row, 0, label)
        enabled = self._centered_checkbox(setting.enabled)
        table.setCellWidget(row, 1, enabled["container"])

        delivery_widget = QWidget()
        delivery = QHBoxLayout(delivery_widget)
        delivery.setContentsMargins(6, 0, 6, 0)
        delivery.setSpacing(10)
        bark = QCheckBox("Bark")
        bark.setChecked(setting.bark)
        desktop = QCheckBox("Desktop")
        desktop.setChecked(setting.desktop)
        history = QCheckBox("History")
        history.setChecked(setting.history)
        delivery.addWidget(bark)
        delivery.addWidget(desktop)
        delivery.addWidget(history)
        delivery.addStretch()
        table.setCellWidget(row, 2, delivery_widget)

        sound_widget = QWidget()
        sound_layout = QHBoxLayout(sound_widget)
        sound_layout.setContentsMargins(6, 0, 6, 0)
        sound_layout.setSpacing(6)
        sound = QCheckBox()
        sound.setToolTip("Enable sound")
        sound.setChecked(setting.sound)
        choice = QComboBox()
        choice.addItems([*BUILT_IN_SOUNDS, *self.config.custom_sounds])
        choice.setCurrentText(setting.sound_name)
        volume = QSpinBox()
        volume.setRange(0, 100)
        volume.setSuffix("%")
        volume.setValue(setting.volume)
        sound_layout.addWidget(sound)
        sound_layout.addWidget(choice, 1)
        sound_layout.addWidget(volume)
        table.setCellWidget(row, 3, sound_widget)

        priority = QComboBox()
        priority.addItems([value.value.title() for value in Priority])
        priority.setCurrentText(setting.priority.value.title())
        table.setCellWidget(row, 4, priority)
        self.category_controls[category] = {
            "enabled": enabled["checkbox"],
            "bark": bark,
            "desktop": desktop,
            "history": history,
            "sound": sound,
            "choice": choice,
            "volume": volume,
            "priority": priority,
        }

    def _set_preview_category(self, category: Category) -> None:
        self.preview_category = category

    @staticmethod
    def _centered_checkbox(checked: bool) -> dict[str, QWidget]:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        box = QCheckBox()
        box.setChecked(checked)
        layout.addStretch()
        layout.addWidget(box)
        layout.addStretch()
        return {"container": container, "checkbox": box}

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _actions(self) -> QHBoxLayout:
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        preview = QPushButton("Preview selected sound")
        preview.clicked.connect(self.preview)
        import_button = QPushButton("Import custom audio")
        import_button.clicked.connect(self.import_sound)
        save = QPushButton("Save Settings")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save)
        buttons.addWidget(preview)
        buttons.addWidget(import_button)
        buttons.addStretch()
        buttons.addWidget(save)
        return buttons

    def preview(self) -> None:
        controls = self.category_controls[self.preview_category]
        self.sounds.play(
            controls["choice"].currentText(),
            controls["volume"].value(),
            self.config.custom_sounds,
        )

    def import_sound(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self, "Import audio", "", "Audio (*.wav *.mp3 *.ogg)"
        )
        if not source:
            return
        try:
            destination = self.sounds.import_file(Path(source))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self.config.custom_sounds[destination.stem] = str(destination)
        for controls in self.category_controls.values():
            controls["choice"].addItem(destination.stem)

    def save(self) -> None:
        if not self.bark_url.text().startswith("https://"):
            QMessageBox.warning(self, "Invalid Bark URL", "Bark requires an HTTPS server URL.")
            return
        fallback_value_changed = False
        if startup_supported():
            requested_startup = self.start_with_windows.isChecked()
            try:
                set_startup_enabled(requested_startup)
                migrate_legacy_startup_entries()
            except OSError as exc:
                if requested_startup:
                    try:
                        set_startup_enabled(False)
                    except OSError:
                        pass
                QMessageBox.warning(self, "Startup update failed", str(exc))
                return
            self.config.start_with_windows = requested_startup
        if self.codex_local_fallback_available:
            requested_fallback = self.codex_local_fallback.isChecked()
            fallback_value_changed = (
                requested_fallback != self.config.codex_local_fallback_enabled
            )
            self.config.codex_local_fallback_enabled = requested_fallback
        self.config.bark_enabled = self.bark_enabled.isChecked()
        self.config.bark_server_url = self.bark_url.text().strip()
        self.config.bark_device_key = self.bark_key.text().strip()
        self.config.quiet_hours_enabled = self.quiet_enabled.isChecked()
        self.config.quiet_start = self.quiet_start.time().toString("HH:mm")
        self.config.quiet_end = self.quiet_end.time().toString("HH:mm")
        self.config.quiet_bark_silent = self.bark_silent.isChecked()
        self.config.quiet_allow_critical = self.critical_bypass.isChecked()
        self.config.duplicate_suppression = self.suppress.isChecked()
        self.config.merge_duplicates = self.merge.isChecked()
        self.config.cooldown_seconds = self.cooldown.value()
        self.config.max_per_minute = self.rate.value()
        self.config.theme = next(
            mode for mode, button in self.appearance_buttons.items() if button.isChecked()
        )
        for category, controls in self.category_controls.items():
            setting = self.config.categories[category.value]
            setting.enabled = controls["enabled"].isChecked()
            setting.bark = controls["bark"].isChecked()
            setting.desktop = controls["desktop"].isChecked()
            setting.history = controls["history"].isChecked()
            setting.sound = controls["sound"].isChecked()
            setting.sound_name = controls["choice"].currentText()
            setting.volume = controls["volume"].value()
            setting.priority = Priority(controls["priority"].currentText().lower())
        self.store.save(self.config)
        if fallback_value_changed and self.fallback_changed is not None:
            self.fallback_changed(self.config.codex_local_fallback_enabled)
        if self.theme_changed is not None:
            self.theme_changed(self.config.theme)
        QMessageBox.information(self, "Settings saved", "Notification settings were saved.")
