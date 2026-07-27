from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication


@dataclass(frozen=True, slots=True)
class Palette:
    bg: str
    elevated: str
    card: str
    hover: str
    pressed: str
    sidebar: str
    input: str
    subtle: str
    accent: str
    accent_hover: str
    accent_dim: str
    text: str
    secondary: str
    dim: str
    border: str
    border_strong: str
    danger: str
    danger_bg: str
    success: str
    success_bg: str
    warning: str
    warning_bg: str


LIGHT = Palette(
    bg="#f3f7fc",
    elevated="#ffffff",
    card="#ffffff",
    hover="#f1f6ff",
    pressed="#e2edfc",
    sidebar="#f1f7ff",
    input="#ffffff",
    subtle="#f8fbff",
    accent="#5d8ff3",
    accent_hover="#4779df",
    accent_dim="#e7f0ff",
    text="#17233a",
    secondary="#5e718c",
    dim="#74819a",
    border="#dce6f2",
    border_strong="#c9d8e9",
    danger="#d92d20",
    danger_bg="#fdecec",
    success="#1f8a4c",
    success_bg="#e9f7ef",
    warning="#b7791f",
    warning_bg="#fff7e8",
)

DARK = Palette(
    bg="#111a2a",
    elevated="#172236",
    card="#19253a",
    hover="#223149",
    pressed="#2a3d59",
    sidebar="#141f31",
    input="#111b2d",
    subtle="#1d2a40",
    accent="#7da6ff",
    accent_hover="#9ab9ff",
    accent_dim="#243958",
    text="#f2f6fc",
    secondary="#b2bfd0",
    dim="#8797ae",
    border="#2b3a51",
    border_strong="#3b4d67",
    danger="#ff8585",
    danger_bg="#4b2730",
    success="#55c684",
    success_bg="#203d32",
    warning="#e9b95e",
    warning_bg="#463923",
)


def is_dark_mode(mode: str) -> bool:
    if mode == "dark":
        return True
    if mode == "light":
        return False
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def palette_for(mode: str) -> Palette:
    return DARK if is_dark_mode(mode) else LIGHT


def stylesheet_for(mode: str) -> str:
    p = palette_for(mode)
    return f"""
        * {{
            font-size: 13px;
            color: {p.text};
        }}
        QMainWindow, QWidget#appShell, QWidget#page, QScrollArea#pageScroll,
        QScrollArea#pageScroll > QWidget > QWidget {{
            background: {p.bg};
        }}
        QFrame#sidebar {{
            background: {p.sidebar};
            border-right: 1px solid {p.border};
        }}
        QLabel#brandTitle {{ font-size: 18px; font-weight: 600; }}
        QLabel#brandSubtitle {{
            color: {p.dim};
            font-size: 10px;
            font-weight: 600;
            letter-spacing: 1px;
        }}
        QPushButton#navButton, QPushButton#utilityButton {{
            min-height: 42px;
            padding: 0 12px;
            text-align: left;
            border: 1px solid transparent;
            border-radius: 10px;
            background: transparent;
            color: {p.secondary};
        }}
        QPushButton#navButton:hover, QPushButton#utilityButton:hover {{
            background: {p.hover};
            color: {p.text};
        }}
        QPushButton#navButton:pressed, QPushButton#utilityButton:pressed {{
            background: {p.pressed};
        }}
        QPushButton#navButton:checked {{
            background: {p.accent_dim};
            border-color: {p.border_strong};
            color: {p.accent};
            font-weight: 600;
        }}
        QPushButton#navButton:focus, QPushButton#utilityButton:focus {{
            border-color: {p.accent};
        }}
        QLabel#pageTitle {{ font-size: 28px; font-weight: 600; }}
        QLabel#pageSubtitle {{ color: {p.secondary}; font-size: 13px; }}
        QLabel#sectionTitle {{ font-size: 16px; font-weight: 600; }}
        QLabel#sectionDescription, QLabel#metadata, QLabel#historyTime {{
            color: {p.secondary};
        }}
        QLabel#fieldLabel {{
            color: {p.dim};
            font-size: 11px;
            font-weight: 600;
        }}
        QFrame#card, QFrame#historyCard {{
            background: {p.card};
            border: 1px solid {p.border};
            border-radius: 12px;
        }}
        QFrame#statusCard {{
            background: {p.card};
            border: 1px solid {p.border};
            border-radius: 12px;
        }}
        QLabel#statusBadge, QLabel#priorityBadge, QLabel#deliveryStatus,
        QLabel#duplicateCount {{
            border-radius: 8px;
            padding: 3px 8px;
            font-size: 11px;
            font-weight: 600;
        }}
        QLabel#statusBadge[state="success"], QLabel#deliveryStatus[state="success"] {{
            background: {p.success_bg};
            color: {p.success};
        }}
        QLabel#statusBadge[state="warning"], QLabel#deliveryStatus[state="warning"] {{
            background: {p.warning_bg};
            color: {p.warning};
        }}
        QLabel#statusBadge[state="neutral"], QLabel#deliveryStatus[state="neutral"],
        QLabel#priorityBadge[priority="normal"], QLabel#priorityBadge[priority="low"],
        QLabel#duplicateCount {{
            background: {p.accent_dim};
            color: {p.accent};
        }}
        QLabel#priorityBadge[priority="high"] {{
            background: {p.warning_bg};
            color: {p.warning};
        }}
        QLabel#priorityBadge[priority="critical"] {{
            background: {p.danger_bg};
            color: {p.danger};
        }}
        QPushButton {{
            min-height: 36px;
            padding: 0 14px;
            border: 1px solid {p.border};
            border-radius: 10px;
            background: {p.card};
        }}
        QPushButton:hover {{ background: {p.hover}; border-color: {p.border_strong}; }}
        QPushButton:pressed {{ background: {p.pressed}; }}
        QPushButton:focus {{ border: 2px solid {p.accent}; }}
        QPushButton:disabled {{ color: {p.dim}; background: {p.subtle}; }}
        QPushButton#primaryButton {{
            background: {p.accent_dim};
            border-color: {p.accent};
            color: {p.accent_hover};
            font-weight: 600;
        }}
        QPushButton#primaryButton:hover {{ background: {p.pressed}; }}
        QPushButton#dangerButton {{ color: {p.danger}; background: {p.danger_bg}; }}
        QPushButton#appearanceButton:checked {{
            color: {p.accent};
            background: {p.accent_dim};
            border: 2px solid {p.accent};
            font-weight: 600;
        }}
        QLineEdit, QTextEdit, QComboBox, QSpinBox, QTimeEdit {{
            min-height: 34px;
            padding: 0 10px;
            background: {p.input};
            border: 1px solid {p.border};
            border-radius: 10px;
            selection-background-color: {p.accent_dim};
        }}
        QTextEdit {{ padding: 10px; }}
        QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover, QTimeEdit:hover {{
            border-color: {p.border_strong};
        }}
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {{
            border: 2px solid {p.accent};
        }}
        QCheckBox {{ spacing: 7px; }}
        QCheckBox::indicator {{ width: 18px; height: 18px; }}
        QTableWidget {{
            background: {p.card};
            alternate-background-color: {p.subtle};
            border: 1px solid {p.border};
            border-radius: 12px;
            gridline-color: {p.border};
            selection-background-color: {p.accent_dim};
        }}
        QHeaderView::section {{
            min-height: 36px;
            padding: 0 10px;
            background: {p.subtle};
            border: 0;
            border-bottom: 1px solid {p.border};
            color: {p.secondary};
            font-size: 11px;
            font-weight: 600;
        }}
        QScrollBar:vertical {{ width: 10px; background: transparent; }}
        QScrollBar::handle:vertical {{
            min-height: 32px;
            border-radius: 5px;
            background: {p.border_strong};
        }}
        QMenuBar, QMenu {{ background: {p.elevated}; }}
        QMenuBar::item:selected, QMenu::item:selected {{ background: {p.accent_dim}; }}
        QDialog {{ background: {p.elevated}; }}
        QLabel#detailTitle {{ font-size: 18px; font-weight: 600; }}
        QLabel#copyFeedback {{ color: {p.success}; min-height: 18px; }}
    """
