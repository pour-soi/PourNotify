from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from pournotify.models import Category, Notification, Priority
from pournotify.services.history import HistoryStore
from pournotify.ui.history import HistoryPage, NotificationDetailsDialog


def app():
    return QApplication.instance() or QApplication([])


def make_store(tmp_path):
    store = HistoryStore(tmp_path / "history.json")
    store.add(
        Notification(Category.SYSTEM_EVENTS, "Short", "compact"),
        "delivered",
        Priority.NORMAL,
    )
    store.add(
        Notification(
            Category.SYSTEM_EVENTS,
            "Long",
            "Hidden search phrase " + "complete original message " * 30,
        ),
        "delivered",
        Priority.CRITICAL,
    )
    duplicate = Notification(Category.SYSTEM_EVENTS, "Duplicate", "same body")
    store.add(duplicate, "delivered", Priority.HIGH)
    store.merge_last(duplicate, Priority.HIGH)
    return store


def test_cards_show_priority_duplicate_and_bottom_padding(tmp_path):
    app()
    page = HistoryPage(make_store(tmp_path))
    page.resize(420, 700)
    page.show()
    QApplication.processEvents()
    assert len(page.cards) == 3
    assert page.BOTTOM_PADDING >= 32
    duplicate = next(card for card in page.cards if card.entry["title"] == "Duplicate")
    assert duplicate.findChild(type(page.copy_feedback), "duplicateCount").text() == "2 duplicates"
    critical = next(card for card in page.cards if card.entry["title"] == "Long")
    assert critical.findChild(type(page.copy_feedback), "priorityBadge").text() == "Critical"
    assert critical.width() <= page.scroll.viewport().width()
    bar = page.scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    QApplication.processEvents()
    last_bottom = page.cards[-1].mapTo(
        page.scroll.viewport(), QPoint(0, page.cards[-1].height())
    ).y()
    assert last_bottom <= page.scroll.viewport().height() - 20
    page.close()


def test_detail_and_copy_use_full_text_without_resetting_search(tmp_path):
    app()
    page = HistoryPage(make_store(tmp_path))
    page.search.setText("hidden search phrase")
    assert len(page.cards) == 1
    entry = page.cards[0].entry
    page.open_details(entry)
    QApplication.processEvents()
    dialog = page.active_dialog
    assert isinstance(dialog, NotificationDetailsDialog)
    assert dialog.message.toPlainText() == entry["message"]
    dialog._copy(page.copy_entry)
    assert QApplication.clipboard().text() == f"{entry['title']}\n\n{entry['message']}"
    assert dialog.copy_feedback.text() == "Copied"
    assert page.search.text() == "hidden search phrase"
    dialog.close()
    page.close()


def test_search_uses_full_message_not_collapsed_preview(tmp_path):
    app()
    page = HistoryPage(make_store(tmp_path))
    page.search.setText("original message")
    assert [card.entry["title"] for card in page.cards] == ["Long"]
    page.close()


def test_history_constructs_with_500_compact_cards(tmp_path):
    app()
    store = HistoryStore(tmp_path / "history.json")
    store._write([
        {
            "time": "2026-07-23T12:00:00-07:00",
            "type": "system_events",
            "title": f"Entry {index}",
            "message": "Compact message",
            "status": "delivered",
        }
        for index in range(500)
    ])
    page = HistoryPage(store)
    assert len(page.cards) == 500
    assert all(card.minimumHeight() == 154 for card in page.cards)
    page.close()
