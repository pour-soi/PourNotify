from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from ..services.content import copy_text, entry_priority, history_preview
from ..services.history import HistoryStore


def priority_label(entry: dict[str, object]) -> str:
    return entry_priority(entry).title()


class NotificationDetailsDialog(QDialog):
    def __init__(
        self,
        entry: dict[str, object],
        copy_callback: Callable[[dict[str, object]], None],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.entry = entry
        self.setWindowTitle("Notification Details")
        self.resize(640, 520)
        layout = QVBoxLayout(self)

        title = QLabel(str(entry.get("title", "")))
        title.setObjectName("detailTitle")
        title.setTextFormat(Qt.PlainText)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        metadata = [
            f"Category: {entry.get('type', 'unknown')}",
            f"Priority: {priority_label(entry)}",
            f"Timestamp: {entry.get('time', '')}",
            f"Status: {entry.get('status', '')}",
        ]
        count = int(entry.get("count", 1))
        if count > 1:
            metadata.append(f"Duplicate count: {count}")
        meta = QLabel("\n".join(metadata))
        meta.setObjectName("detailMetadata")
        meta.setTextFormat(Qt.PlainText)
        meta.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        layout.addWidget(meta)

        self.message = QTextEdit()
        self.message.setObjectName("detailMessage")
        self.message.setReadOnly(True)
        self.message.setAcceptRichText(False)
        self.message.setPlainText(str(entry.get("message", "")))
        layout.addWidget(self.message, 1)

        actions = QHBoxLayout()
        self.copy_feedback = QLabel("")
        self.copy_feedback.setObjectName("detailCopyFeedback")
        self.copy_feedback.setStyleSheet("color: #35664b;")
        actions.addWidget(self.copy_feedback)
        actions.addStretch()
        copy_button = QPushButton("Copy")
        copy_button.clicked.connect(lambda: self._copy(copy_callback))
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        actions.addWidget(copy_button)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    def _copy(self, copy_callback: Callable[[dict[str, object]], None]) -> None:
        copy_callback(self.entry)
        self.copy_feedback.setText("Copied")
        QTimer.singleShot(1500, lambda: self.copy_feedback.setText(""))


class HistoryCard(QFrame):
    def __init__(
        self,
        entry: dict[str, object],
        on_details: Callable[[dict[str, object]], None],
        on_copy: Callable[[dict[str, object]], None],
    ):
        super().__init__()
        self.entry = entry
        self.setObjectName("historyCard")
        self.setMinimumHeight(154)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setStyleSheet(
            "QFrame#historyCard { background: white; border: 1px solid #dfe3e8;"
            " border-radius: 10px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        header = QHBoxLayout()
        title = QLabel(str(entry.get("title", "")))
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        title.setMinimumWidth(0)
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        header.addWidget(title, 1)
        badge = QLabel(priority_label(entry))
        badge.setObjectName("priorityBadge")
        badge.setProperty("priority", entry_priority(entry))
        badge.setAlignment(Qt.AlignCenter)
        colors = {
            "normal": ("#eef1f4", "#30343a"),
            "high": ("#fff0c2", "#6b4b00"),
            "critical": ("#ffe1e1", "#8a1c1c"),
            "low": ("#e6f2ff", "#235a85"),
        }
        background, foreground = colors[entry_priority(entry)]
        badge.setStyleSheet(
            f"background: {background}; color: {foreground}; border-radius: 8px;"
            " padding: 3px 8px; font-weight: 600;"
        )
        header.addWidget(badge)
        layout.addLayout(header)

        preview = QLabel(history_preview(str(entry.get("message", ""))))
        preview.setObjectName("historyPreview")
        preview.setTextFormat(Qt.PlainText)
        preview.setWordWrap(True)
        preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        preview.setMaximumHeight(88)
        preview.setMinimumWidth(0)
        layout.addWidget(preview)

        footer = QHBoxLayout()
        time_label = QLabel(str(entry.get("time", "")))
        time_label.setStyleSheet("color: #66707a;")
        time_label.setMinimumWidth(0)
        footer.addWidget(time_label)
        count = int(entry.get("count", 1))
        if count > 1:
            count_label = QLabel(f"{count} duplicates")
            count_label.setObjectName("duplicateCount")
            footer.addWidget(count_label)
        footer.addStretch()
        layout.addLayout(footer)

        actions = QHBoxLayout()
        actions.addStretch()
        details = QPushButton("View details")
        details.clicked.connect(lambda: on_details(entry))
        copy_button = QPushButton("Copy")
        copy_button.clicked.connect(lambda: on_copy(entry))
        actions.addWidget(details)
        actions.addWidget(copy_button)
        layout.addLayout(actions)


class HistoryPage(QWidget):
    BOTTOM_PADDING = 40

    def __init__(self, history: HistoryStore):
        super().__init__()
        self.history = history
        self.cards: list[HistoryCard] = []
        self.active_dialog: NotificationDetailsDialog | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search notification history")
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search, 1)
        export = QPushButton("Export")
        export.clicked.connect(self.export_history)
        clear = QPushButton("Clear history")
        clear.clicked.connect(self.clear_history)
        top.addWidget(export)
        top.addWidget(clear)
        layout.addLayout(top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setMinimumWidth(0)
        self.content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.card_layout = QVBoxLayout(self.content)
        self.card_layout.setContentsMargins(2, 2, 2, self.BOTTOM_PADDING)
        self.card_layout.setSpacing(10)
        self.card_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)

        self.copy_feedback = QLabel("")
        self.copy_feedback.setObjectName("copyFeedback")
        self.copy_feedback.setStyleSheet("color: #35664b; min-height: 18px;")
        layout.addWidget(self.copy_feedback)
        self.refresh()

    def matching_entries(self) -> list[dict[str, object]]:
        query = self.search.text().strip().casefold()
        entries = reversed(self.history.read())
        if not query:
            return list(entries)
        return [
            entry
            for entry in entries
            if query in str(entry.get("title", "")).casefold()
            or query in str(entry.get("message", "")).casefold()
            or query in str(entry.get("type", "")).casefold()
            or query in str(entry.get("status", "")).casefold()
        ]

    def refresh(self) -> None:
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cards = [
            HistoryCard(entry, self.open_details, self.copy_entry)
            for entry in self.matching_entries()
        ]
        for card in self.cards:
            self.card_layout.addWidget(card)

    def open_details(self, entry: dict[str, object]) -> None:
        self.active_dialog = NotificationDetailsDialog(entry, self.copy_entry, self)
        self.active_dialog.open()

    def copy_entry(self, entry: dict[str, object]) -> None:
        QApplication.clipboard().setText(copy_text(entry))
        self.copy_feedback.setText("Copied")
        QTimer.singleShot(1500, lambda: self.copy_feedback.setText(""))

    def clear_history(self) -> None:
        result = QMessageBox.question(
            self, "Clear history", "Clear all notification history?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if result == QMessageBox.Yes:
            self.history.clear()
            self.refresh()

    def export_history(self) -> None:
        target, selected = QFileDialog.getSaveFileName(
            self,
            "Export history",
            "notifications.json",
            "JSON (*.json);;CSV (*.csv)",
        )
        if not target:
            return
        path = Path(target)
        if not path.suffix:
            path = path.with_suffix(".csv" if selected.startswith("CSV") else ".json")
        self.history.export(path)
