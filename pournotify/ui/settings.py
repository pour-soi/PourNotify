from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
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


class SettingsPage(QWidget):
    def __init__(self, config: AppConfig, store: ConfigStore, sounds: SoundManager):
        super().__init__()
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.config, self.store, self.sounds = config, store, sounds
        layout = QVBoxLayout(self)
        bark = QGroupBox("Bark")
        bark.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        bark_layout = QGridLayout(bark)
        self.bark_enabled = QCheckBox("Enable Bark")
        self.bark_enabled.setChecked(config.bark_enabled)
        self.bark_url = QLineEdit(config.bark_server_url)
        self.bark_key = QLineEdit(config.bark_device_key)
        self.bark_key.setEchoMode(QLineEdit.Password)
        bark_layout.addWidget(self.bark_enabled, 0, 0, 1, 2)
        bark_layout.addWidget(QLabel("HTTPS server"), 1, 0)
        bark_layout.addWidget(self.bark_url, 1, 1)
        bark_layout.addWidget(QLabel("Device key"), 2, 0)
        bark_layout.addWidget(self.bark_key, 2, 1)
        layout.addWidget(bark)

        quiet = QGroupBox("Quiet Hours")
        quiet.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        quiet_layout = QGridLayout(quiet)
        self.quiet_enabled = QCheckBox("Enable")
        self.quiet_enabled.setChecked(config.quiet_hours_enabled)
        self.quiet_start, self.quiet_end = QTimeEdit(), QTimeEdit()
        self.quiet_start.setTime(self.quiet_start.time().fromString(config.quiet_start, "HH:mm"))
        self.quiet_end.setTime(self.quiet_end.time().fromString(config.quiet_end, "HH:mm"))
        self.bark_silent = QCheckBox("Make Bark silent")
        self.bark_silent.setChecked(config.quiet_bark_silent)
        self.critical_bypass = QCheckBox("Critical notifications may bypass")
        self.critical_bypass.setChecked(config.quiet_allow_critical)
        quiet_layout.addWidget(self.quiet_enabled, 0, 0)
        quiet_layout.addWidget(QLabel("From"), 1, 0)
        quiet_layout.addWidget(self.quiet_start, 1, 1)
        quiet_layout.addWidget(QLabel("To"), 1, 2)
        quiet_layout.addWidget(self.quiet_end, 1, 3)
        quiet_layout.addWidget(self.bark_silent, 2, 0, 1, 2)
        quiet_layout.addWidget(self.critical_bypass, 2, 2, 1, 2)
        layout.addWidget(quiet)

        anti = QGroupBox("Anti-spam")
        anti.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        anti_layout = QGridLayout(anti)
        self.suppress = QCheckBox("Suppress duplicates")
        self.suppress.setChecked(config.duplicate_suppression)
        self.merge = QCheckBox("Merge duplicates")
        self.merge.setChecked(config.merge_duplicates)
        self.cooldown = QSpinBox()
        self.cooldown.setRange(0, 86400)
        self.cooldown.setValue(config.cooldown_seconds)
        self.rate = QSpinBox()
        self.rate.setRange(1, 120)
        self.rate.setValue(config.max_per_minute)
        anti_layout.addWidget(self.merge, 0, 0)
        anti_layout.addWidget(self.suppress, 0, 1)
        anti_layout.addWidget(QLabel("Cooldown seconds"), 0, 2)
        anti_layout.addWidget(self.cooldown, 0, 3)
        anti_layout.addWidget(QLabel("Maximum per minute"), 0, 4)
        anti_layout.addWidget(self.rate, 0, 5)
        layout.addWidget(anti)

        self.table = QTableWidget(len(Category), 9)
        self.table.setMinimumWidth(0)
        self.table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.table.setHorizontalHeaderLabels(
            ["Category", "Enabled", "Bark", "Desktop", "Sound", "History",
             "Sound choice", "Volume", "Priority"]
        )
        for row, category in enumerate(Category):
            setting = config.categories[category.value]
            label = QTableWidgetItem(CATEGORY_LABELS[category])
            label.setData(Qt.UserRole, category.value)
            self.table.setItem(row, 0, label)
            for column, checked in enumerate(
                (setting.enabled, setting.bark, setting.desktop, setting.sound, setting.history), 1
            ):
                box = QCheckBox()
                box.setChecked(checked)
                box.setStyleSheet("margin-left:18px")
                self.table.setCellWidget(row, column, box)
            choice = QComboBox()
            choice.addItems([*BUILT_IN_SOUNDS, *config.custom_sounds])
            choice.setCurrentText(setting.sound_name)
            self.table.setCellWidget(row, 6, choice)
            volume = QSpinBox()
            volume.setRange(0, 100)
            volume.setValue(setting.volume)
            self.table.setCellWidget(row, 7, volume)
            priority = QComboBox()
            priority.addItems([value.value.title() for value in Priority])
            priority.setCurrentText(setting.priority.value.title())
            self.table.setCellWidget(row, 8, priority)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.table)
        buttons = QGridLayout()
        preview = QPushButton("Preview selected sound")
        preview.clicked.connect(self.preview)
        import_button = QPushButton("Import custom audio")
        import_button.clicked.connect(self.import_sound)
        save = QPushButton("Save Settings")
        save.clicked.connect(self.save)
        buttons.addWidget(preview, 0, 0)
        buttons.addWidget(import_button, 0, 1)
        buttons.addWidget(save, 0, 2)
        layout.addLayout(buttons)

    def preview(self) -> None:
        row = max(0, self.table.currentRow())
        self.sounds.play(
            self.table.cellWidget(row, 6).currentText(),
            self.table.cellWidget(row, 7).value(),
            self.config.custom_sounds,
        )

    def import_sound(self) -> None:
        source, _ = QFileDialog.getOpenFileName(self, "Import audio", "", "Audio (*.wav *.mp3 *.ogg)")
        if not source:
            return
        try:
            destination = self.sounds.import_file(Path(source))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self.config.custom_sounds[destination.stem] = str(destination)
        for row in range(self.table.rowCount()):
            self.table.cellWidget(row, 6).addItem(destination.stem)

    def save(self) -> None:
        if not self.bark_url.text().startswith("https://"):
            QMessageBox.warning(self, "Invalid Bark URL", "Bark requires an HTTPS server URL.")
            return
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
        for row, category in enumerate(Category):
            setting = self.config.categories[category.value]
            values = [self.table.cellWidget(row, column).isChecked() for column in range(1, 6)]
            setting.enabled, setting.bark, setting.desktop, setting.sound, setting.history = values
            setting.sound_name = self.table.cellWidget(row, 6).currentText()
            setting.volume = self.table.cellWidget(row, 7).value()
            setting.priority = Priority(self.table.cellWidget(row, 8).currentText().lower())
        self.store.save(self.config)
        QMessageBox.information(self, "Settings saved", "Notification settings were saved.")
