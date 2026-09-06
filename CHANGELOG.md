# Changelog

## 1.0.6

- Supported scope: Finished and Input Required. Both user-facing stop reasons deliver short
  **Codex Needs Attention · Project** alerts instead of copying assistant output.
- Added an optional Windows read-only local observer to recover missed notify-hook events, with
  startup baselining and shared thread/turn deduplication across both intake paths.
- Suppressed internal subagents, title/description/UI metadata, intermediate progress and unknown
  thread sources; retained privacy-safe diagnostics and separate Input Required History entries.
- Improved required-input detection using reconstructed task context, including Chinese requests
  independent of terminal punctuation. Finished and Input Required passed physical validation in
  the approved candidate flows with one alert per channel and no duplicates observed.
- Approval Required is disabled by default and retained only for configuration compatibility.
  Real pending/resolved permission approval waits are not reliably supported: the current Desktop
  local sources do not expose a reliable read-only approval lifecycle. No heuristic is added.
- Codex notify events are turn-level, not explicit task-terminal signals. Detection remains
  conservative and may suppress ambiguous or unverified events; perfect detection is not claimed.

## 1.0.5

- Added conservative Codex lifecycle classification: blocked owner-action turns notify through
  **Codex Needs Your Input** or **Codex Approval Required**, while high-confidence final results
  notify through **Codex Task Completed**.
- Suppressed Codex Desktop activity summaries, title generation and updates, UI and description
  metadata, intermediate analysis, checkpoints, and other clearly in-progress turns.
- Redacted private prompt and assistant content from notification diagnostics while recording stable
  lifecycle reasons and per-channel delivery attempts and results.
- Prevented duplicate lifecycle notifications in the validated input-required-then-completed flow.
- Codex currently exposes turn-level notify events rather than an explicit task-terminal lifecycle
  signal, so final-result detection remains intentionally conservative rather than perfect.

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
