<p align="center">
  <img src="pournotify/resources/icons/pournotify-128.png" width="96" alt="PourNotify">
</p>

<h1 align="center">PourNotify</h1>

<p align="center">
  Local-first desktop, sound, Bark, and History notifications for Codex.
</p>

<p align="center">
  <a href="https://github.com/pour-soi/PourNotify/releases/tag/v1.0.5"><img alt="Latest Release" src="https://img.shields.io/github/v/release/pour-soi/PourNotify?display_name=tag&amp;sort=semver"></a>
  <a href="#download"><img alt="Windows" src="https://img.shields.io/badge/Windows-supported-3578E5?logo=windows&amp;logoColor=white"></a>
  <a href="#project-status"><img alt="macOS" src="https://img.shields.io/badge/macOS-CI_build-6B7280?logo=apple&amp;logoColor=white"></a>
  <a href="https://github.com/pour-soi/PourNotify/actions/workflows/build.yml"><img alt="CI" src="https://github.com/pour-soi/PourNotify/actions/workflows/build.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/License-MIT-2E7D32.svg"></a>
</p>

<p align="center">
  <a href="https://github.com/pour-soi/PourNotify/releases/download/v1.0.5/PourNotify-v1.0.5-Windows.exe">Download</a> •
  <a href="https://github.com/pour-soi/PourNotify/releases/tag/v1.0.5">Releases</a> •
  <a href="#quick-start">Documentation</a> •
  <a href="https://github.com/pour-soi/PourNotify/tree/v1.0.5">Source Code</a>
</p>

![PourNotify dashboard showing Codex, Bark, desktop, History, and Diagnostics status](docs/images/pournotify-dashboard.jpg)

## What's new in v1.0.5

- Notifies once when Codex needs required owner input or approval, and once when a later final result
  is classified as a high-confidence completion.
- Suppresses internal activity summaries, title and UI metadata, description metadata, intermediate
  analysis, checkpoints, and other clearly in-progress turns.
- Keeps diagnostics useful while excluding raw private prompts and assistant output.
- Uses conservative classification because Codex notify hooks are turn-level events and do not
  provide an explicit task-terminal lifecycle signal.

## Overview

PourNotify receives Codex events and routes user-facing attention transitions through the channels
enabled for each category. Notification Test uses the same dispatcher as real Codex events.

Configuration, History, and diagnostics stay on your computer. PourNotify has no hosted backend or
account requirement.

## Development draft: Codex needs attention

The unreleased development branch treats `needs_attention` as the primary Codex lifecycle state.
A user-facing turn needs attention when Codex has stopped and is waiting because the current work
finished, required input is missing, or approval is required. Known internal housekeeping,
automatically continuing progress, and ambiguous turns remain silent.

Existing configuration keys remain compatible: `finished` uses `task_completed`, while
`input_required` and `approval_required` retain their existing categories. All three produce a
short **Codex Needs Attention · Project** title (when a safe project name is available) and a
one-sentence reason. The full Codex response stays in Codex and is not copied into Desktop, Bark,
or new History entries.

### Approval validation limitation (PR #6)

Finished and Input Required passed the recorded real-task physical checks. Formal, mid-turn
permission approval waits are **not currently supported reliably**: the real Case 3 approval
prompt produced no notification. The `approval_required` category remains compatible, but its
existence and text classification do not establish detection of a live permission gate.

Codex's app-server protocol provides `item/commandExecution/requestApproval` and
`serverRequest/resolved`, with thread, turn, item and request identities. However, the installed
Desktop's inspected rollout, database and log sources do not expose a usable pending/resolved
approval sequence to this observer. The Desktop maintains live conversation requests; a request
for `require_escalated`, an `inProgress` turn, or a missing tool result is not proof that owner
approval is pending. No heuristic fallback is added for those signals.

A future adapter requires an authoritative read-only pending snapshot/event stream and resolution
tracking, per-request deduplication across intake paths, and startup baselining without replay.
Approval resolution must not itself mean completion or consume a later finished transition's
identity. Approve/reject/cancel, restart and parallel-thread behavior remain unvalidated until
that source is available. PR #6 is not ready for full acceptance on the current Case 3 criteria.
See the [official approval protocol](https://learn.chatgpt.com/docs/app-server#approvals).

## Features

| | |
| --- | --- |
| **Desktop Notifications**<br>Native banners and Notification Center entries. | **Bark Delivery**<br>HTTPS pushes through your configured Bark server. |
| **Notification History**<br>Search, copy, inspect, and export local records. | **Quiet Hours**<br>Control interruptions with critical-event exceptions. |
| **IPC**<br>Single-resident routing for Codex and second-process events. | **Diagnostics**<br>Rotating JSONL logs with Bark credentials redacted. |
| **Custom Sounds**<br>Choose sound and volume independently by category. | **Background Startup**<br>Start silently at login and remain available in the tray. |

## Download

The latest stable release is **v1.0.5**.

- **Windows:** download [`PourNotify-v1.0.5-Windows.exe`](https://github.com/pour-soi/PourNotify/releases/download/v1.0.5/PourNotify-v1.0.5-Windows.exe).
- **All releases:** visit [GitHub Releases](https://github.com/pour-soi/PourNotify/releases).
- The automatically generated source archives are source code, not the normal Windows executable.
- Windows and macOS builds pass in CI. Physical macOS runtime validation is still pending, and the
  v1.0.5 release currently publishes only the Windows executable.

## Quick start

1. Download and launch the latest Windows release.
2. Configure desktop, sound, History, and optional Bark delivery in **Settings**.
3. Optionally enable **Start PourNotify automatically when I sign in** for silent tray startup.
4. Connect the global Codex notification hook using the example below.
5. Run **Notification Test**, then let a user-facing Codex task stop to verify delivery.

When PourNotify is already running, launching it normally opens the existing window. Login startup
does not open the window or create a second resident.

The packaged Windows application does not require a separate Python installation.

## Codex integration

PourNotify accepts one CLI argument: `--notify <Codex JSON payload>`. A stable installation path is
important because Codex invokes that executable after every supported event.

If Codex already uses the `codex-computer-use` `turn-ended` wrapper, keep the wrapper and set
PourNotify as its previous notification command. In the global Codex `config.toml`, preserve the
existing wrapper path and use this structure:

```toml
notify = [
  "<CODEX_COMPUTER_USE_PATH>",
  "turn-ended",
  "--previous-notify",
  "[\"<POURNOTIFY_INSTALL_PATH>\\\\PourNotify.exe\",\"--notify\"]",
]
```

Replace both placeholders with stable local paths. On Windows, a suitable PourNotify location is
under `%LOCALAPPDATA%\Programs\PourNotify`; do not point the hook at a project's temporary `dist`
directory.

The wrapper preserves Codex's existing turn-completion handling and forwards the payload to
PourNotify. Keep Bark configured inside PourNotify rather than adding a second independent Bark
notification script, which would duplicate deliveries.

When PourNotify is already resident, the temporary invocation sends the JSON payload to it through
local Qt IPC and exits. If no resident process accepts the connection, the invocation starts a
hidden temporary instance, processes the same payload locally, and exits after delivery.

On Windows, **Recover missed Codex attention events with the local observer** is an optional,
default-off supplement to the hook. The resident reads only newly appended records from
`%USERPROFILE%\.codex\sessions\YYYY\MM\DD\rollout-*.jsonl`, baselines existing records without
replay, and sends qualifying turns through the same attention classifier and dispatcher. A
persistent thread/turn ledger prevents a hook event and its fallback copy from producing two
notifications. The fallback does not replace or disable the normal notify command.

Both intake paths verify the local rollout's structural thread source before notifying. Internal
collaboration subagents never become owner-attention alerts, even when their external notify payload
looks like a substantive final response.

> PourNotify currently parses Codex `agent-turn-complete` hook events. Codex does not provide an
> explicit attention or task-terminal field in the documented notify contract. PourNotify therefore
> combines stable thread/turn identity, user-facing stop evidence, explicit owner-action wording,
> and conservative internal/progress suppression. Ambiguous events remain silent.

## Notification controls

The Settings page groups the three Codex attention reasons—Finished, Input Required, and Approval
Required—under **Notify me when Codex needs my attention**. Their existing configuration categories
remain intact for backward compatibility. Each reason keeps its own settings for:

- enabled state;
- desktop, Bark, sound, and History delivery;
- selected sound and volume;
- priority.

Global settings add quiet hours, Bark silence during quiet hours, critical-event exceptions,
cooldowns, per-minute limits, and duplicate suppression or merging. Unrelated system and quota
categories remain in a separate settings table. Category names remain application configuration
rather than a promised public API.

## History and diagnostics

History is stored locally and can be searched, copied, cleared, or exported as JSON or CSV. Generic
notifications preserve their complete message. New Codex attention entries intentionally store only
the same short reason sent to Desktop and Bark, never the complete assistant response.

**Help > Open Notification Diagnostics** opens the local diagnostics directory. Each received hook
or fallback event produces a JSONL record containing its source, safe thread/turn identity,
attention state and reason, classification and dedupe results, channel attempts and results, HTTP
status, duration, and any exception. Logs rotate automatically and never include the configured
Bark device key.

## Privacy

- PourNotify has no hosted backend, user account, telemetry, or browser cookies.
- Configuration, notification History, and diagnostic logs remain in the local application-data
  directory unless you explicitly export History.
- PourNotify does not collect or store full Codex conversations. Codex attention History stores only
  a fixed short reason when that category is enabled. Diagnostics store structural event fields,
  classification reasons, and delivery results without raw prompts or assistant output.
- When the optional fallback is enabled, prompt and final-answer text is inspected transiently in
  memory by the same lifecycle classifier. The fallback ledger stores only thread/turn identity,
  event source, and claim time; it does not store conversation text.
- Bark delivery sends the notification title and body to the HTTPS Bark server you configure.
- The Bark device key is stored in local configuration. Never commit that file or paste the key into
  issues, logs, screenshots, or examples.
- Bark responses are redacted before diagnostics are written, and automated coverage verifies that
  the device key is absent from diagnostic records.

## Development

PourNotify requires Python 3.11 or newer for source development.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Run the application from source:

```powershell
python -m pournotify
```

Run the repository checks:

```powershell
python -m ruff check .
python -m pytest
```

Create a clean PyInstaller build (the script runs the full test suite first):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

Build output is written to `dist/`. The same test, Ruff, and PyInstaller commands run on
`windows-latest` and `macos-latest` in GitHub Actions.

## Project status

- Latest stable release: **v1.0.5**
- Windows runtime validation: complete
- Silent Windows login startup and single-resident behavior: validated
- Windows toast, Notification Center retention, sound, Bark, History, Diagnostics, and IPC:
  validated
- Windows and macOS CI jobs: passing
- Physical macOS runtime validation: pending

## Contributing

1. Fork the repository.
2. Create a focused branch for the change.
3. Keep the diff scoped and add or update meaningful tests when behavior changes.
4. Run Ruff and the full pytest suite.
5. Open a pull request describing the change and its validation.

## License

PourNotify is available under the [MIT License](LICENSE).
