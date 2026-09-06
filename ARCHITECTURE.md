# Architecture

PourNotify uses a small dependency-injected service boundary:

`Codex or quota provider -> Notification -> NotificationDispatcher -> desktop / Bark / sound / history`

The dispatcher is the policy boundary for category settings, quiet hours, priorities, duplicate
cooldowns, and rate limiting. UI tests and real integrations submit the same `Notification` model.
Configuration and history are human-readable atomic JSON files under the platform application-data
folder. Future providers should translate their events into `Notification` objects without adding
delivery policy.

The dispatcher also canonicalizes known system titles and applies delivery-only message truncation.
Generic History retains the complete original text. Codex attention notifications are normalized
before the dispatcher to a short project-qualified title and one-sentence reason, so assistant
output never enters Desktop, Bark, or new Codex History records. The history UI derives bounded,
non-Markdown plain-text previews at render time.

Codex notify invocations first attempt a local `QLocalSocket` connection to the running app. If no
server exists, the same executable performs a hidden one-shot dispatch. Deduplication identifiers
and recent delivery timestamps are persisted in history so cooldown, merge, and rate controls remain
effective across process boundaries. PourNotify is the only Bark sender in this route.

The primary Codex state is `needs_attention`, with a reason of `finished`, `input_required`, or
`approval_required`. The supported release scope is Finished and Input Required; approval remains
an internal compatibility category, default-off, not reliable live permission-wait detection.
Known automatically continuing progress remains working; internal and ambiguous
turns are silent. The external notify path first resolves the rollout's authoritative
`thread_source`; subagent and unknown sources fail closed before content classification. The
external path and local fallback then normalize into the same attention classifier and map reasons
onto the existing `task_completed`, `input_required`, and `approval_required` configuration
categories.

The optional Windows Codex fallback is resident-only and default-off. Its selected source is the
append-only local rollout JSONL tree under `%USERPROFILE%\.codex\sessions`. This source was selected
because it is read-only, records stable session/turn identity plus turn start, final user-facing
message, and `task_complete`, and is closer to lifecycle activity than local index databases. A
background worker baselines existing files, then polls every five seconds and reads only appended
bytes, bounded to 512 KiB per file and 2 MiB per poll. Existing terminal turns are never replayed;
newly discovered files require a validated post-baseline `completed_at` value.

Observed stops are normalized to the same `agent-turn-complete` shape used by the hook. Both paths
claim a shared SQLite ledger key (`codex:<thread-id>:<turn-id>`) before dispatch, providing
cross-process at-most-once routing in either arrival order. Each file and turn has independent state,
so parallel tasks never share a global idle inference. Diagnostics persist structural identity and
decisions, while prompt and assistant text is kept only in memory for classification. Codex-app
follow-ups are accepted only from the exact delegated message structure for the matching turn; the
source thread ID and wrapper are not emitted.

The official notify configuration documents only that Codex invokes a command with a JSON payload;
it does not document an explicit attention/task-terminal field. The rollout JSONL schema is also an
internal Codex Desktop format rather than a documented lifecycle API. Unknown, malformed,
missing-timestamp, subagent, aborted, and ambiguous records fail closed and produce safe diagnostics.
A missing or unreadable rollout identity also suppresses the hook event; this intentionally favors
avoiding internal-agent false positives over delivering an unverifiable stop when local state has
drifted or disappeared.
A formal user-facing text request for approval can be classified; a native approval pause that has
no persisted terminal turn record cannot be observed reliably by this fallback.
