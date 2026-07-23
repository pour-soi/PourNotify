# PourNotify

PourNotify is a lightweight, local-first Windows and macOS notification center for Codex.
It supports native desktop notifications, Bark delivery to iPhone, per-category sounds,
quiet hours, notification history, and anti-spam controls. No telemetry, cloud backend,
browser cookies, or conversation storage are used.

## Run

Requires Python 3.11 or newer:

```powershell
python -m pip install -e ".[dev]"
python -m pournotify
```

Codex can call the same production pipeline using:

```text
python -m pournotify --notify <Codex JSON payload>
```

Configure that command as Codex's `notify` command using an absolute Python executable and
absolute project path. Unknown or malformed future event types are ignored safely.

When the desktop app is already running, notify invocations forward payloads over local Qt IPC.
When it is stopped, a hidden transient instance dispatches the event and exits. Persisted
deduplication prevents repeated callbacks from creating multiple history entries. Bark delivery
must remain inside PourNotify; do not configure a second Bark script in the Codex notify chain.

## Notification controls

Every notification category independently controls enabled state, Bark, desktop, sound,
history, selected sound, volume, and priority. Quiet hours preserve desktop banners while
muting sound; critical and explicitly configured exceptions can bypass quiet hours.

History uses bounded plain-text previews while preserving the complete original notification.
Each entry has priority and duplicate-count labels, full selectable details, one-click Copy,
full-content search, and lossless JSON or CSV export.

The Notification Test tab simulates supported events through the exact dispatcher used by
Codex and quota providers.

## Build

```powershell
./scripts/build.ps1
```

Windows builds are produced locally in `dist/`. The GitHub workflow prepares both Windows and
macOS builds; a macOS artifact must only be claimed after the macOS job actually succeeds.
