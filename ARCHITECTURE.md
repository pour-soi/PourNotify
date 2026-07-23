# Architecture

PourNotify uses a small dependency-injected service boundary:

`Codex or quota provider -> Notification -> NotificationDispatcher -> desktop / Bark / sound / history`

The dispatcher is the policy boundary for category settings, quiet hours, priorities, duplicate
cooldowns, and rate limiting. UI tests and real integrations submit the same `Notification` model.
Configuration and history are human-readable atomic JSON files under the platform application-data
folder. Future providers should translate their events into `Notification` objects without adding
delivery policy.

The dispatcher also canonicalizes known system titles and applies delivery-only message truncation.
History retains the complete original text. The history UI derives bounded, non-Markdown plain-text
previews at render time, so search, details, Copy, duplicate merging, and exports remain lossless.

Codex notify invocations first attempt a local `QLocalSocket` connection to the running app. If no
server exists, the same executable performs a hidden one-shot dispatch. Deduplication identifiers
and recent delivery timestamps are persisted in history so cooldown, merge, and rate controls remain
effective across process boundaries. PourNotify is the only Bark sender in this route.
