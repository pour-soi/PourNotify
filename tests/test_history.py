import csv
import json

from pournotify.models import Category, Notification, Priority
from pournotify.services.history import HistoryStore


def test_history_retains_configured_limit_and_exports(tmp_path):
    store = HistoryStore(tmp_path / "history.json", limit=2)
    for index in range(3):
        store.add(
            Notification(Category.SYSTEM_EVENTS, f"Title {index}", "Message"),
            "delivered",
            Priority.NORMAL,
        )
    assert [item["title"] for item in store.read()] == ["Title 1", "Title 2"]
    destination = tmp_path / "export.json"
    store.export(destination)
    exported = json.loads(destination.read_text(encoding="utf-8"))
    assert exported[-1]["message"] == "Message"
    assert exported[-1]["priority"] == "normal"
    assert exported[-1]["count"] == 1


def test_json_and_csv_export_preserve_complete_original(tmp_path):
    original = "Complete original\n" + "X" * 500
    store = HistoryStore(tmp_path / "history.json")
    store.add(
        Notification(Category.SYSTEM_EVENTS, "Export", original),
        "delivered",
        Priority.HIGH,
    )
    json_path, csv_path = tmp_path / "out.json", tmp_path / "out.csv"
    store.export(json_path)
    store.export(csv_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))[0]["message"] == original
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["message"] == original
    assert row["priority"] == "high"
