# Changelog

## 1.0.4

- Replaced the application, window, taskbar, tray, notification, and executable identity with the
  owner-approved paper-airplane artwork and multi-resolution Windows icon assets.
- Added an explicit `--background` login-startup mode that initializes the resident tray, IPC, and
  notification services without opening the main window.
- Added a default-off Windows startup setting that registers one quoted stable executable command,
  safely refreshes existing PourNotify registration, and preserves normal manual-launch behavior.

## 1.0.3

- Added JSONL notification diagnostics with rotation and direct log-folder access.
- Redesigned the desktop interface around the Pour Design System with stable sidebar navigation,
  Dashboard, Notification Test, History, Settings, and system/light/dark appearance.
- Preserved all 13 notification categories and existing Codex, desktop, sound, Bark, History,
  diagnostics, IPC, duplicate-suppression, quiet-hours, configuration, and tray behavior.

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
