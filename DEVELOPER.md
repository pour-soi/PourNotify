# Developer Guide

Install with `python -m pip install -e ".[dev]"`, run `python -m pytest`, and format/check with
`python -m ruff check .`. Public APIs live in `models.py`; delivery policy belongs only in
`services/dispatcher.py`. Do not log Bark keys or add private quota scraping.

## Windows notification verification

- Confirm the PourNotify tray icon is visible.
- Complete a real Codex task and confirm a Windows desktop banner appears.
- Confirm the notification remains in Windows Notification Center.
- Confirm the configured notification sound still plays.
- Confirm the Bark notification still arrives on the configured iPhone.
