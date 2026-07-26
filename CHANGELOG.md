# Changelog

## 1.0.2

- Pinned Ruff 0.16.0 and resolved its findings so local and CI lint gates remain reproducible.

## 1.0.1

- Added a packaged application icon so Windows tray notifications are registered and displayed.
- Changed History delivery status to `attempted` or `attempted_with_errors:*` unless delivery is
  independently confirmed.
- Added source and frozen-build icon resource coverage plus a Windows notification checklist.

## 1.0.0

- Added independently configurable notification categories.
- Added desktop, Bark, sound, quiet-hours, priority, anti-spam, history, and test pipelines.
- Added Codex completion parsing, local JSON configuration, Windows packaging, and macOS CI preparation.
- Added collapsed history cards, selectable full details, one-click Copy, priority and duplicate
  metadata, canonical system titles, readable plain-text previews, and lossless CSV export.
