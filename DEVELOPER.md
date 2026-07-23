# Developer Guide

Install with `python -m pip install -e ".[dev]"`, run `python -m pytest`, and format/check with
`python -m ruff check .`. Public APIs live in `models.py`; delivery policy belongs only in
`services/dispatcher.py`. Do not log Bark keys or add private quota scraping.
