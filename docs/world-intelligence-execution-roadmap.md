# World Intelligence Execution Roadmap

This file turns the remaining high-level World Intelligence roadmap into an
implementation sequence.  The canonical product and epistemic requirements
remain in `docs/world-intelligence-roadmap.md`; this document defines the next
bounded delivery prompts, their exclusions, and their acceptance gates.

## Current decision

Corrective Step 7 must be stabilized before regional baselines, change signals,
forecast promotion, the Jarvis monitor, watchlists, or alerts advance. Article
collection, fair scheduling, bounded fresh capacity, and article-pipeline load
shedding are live. Semantic framing still trails captured evidence, and
cross-publisher framing remains unavailable until at least two assessed
publishers are attached to the same canonical event.

All full-text, semantic-framing, and event-comparison features remain in shadow.
They must not alter factual publisher credibility, canonical factual claims,
notifications, or Entity Core actions.

## Delivery sequence

1. **Implemented and live: Step 7 scheduler fairness and acquisition
   backpressure.**
2. **Implemented and live: bounded fresh-development fast path and reserved
   reasoning capacity.**
3. **Implemented and live: workload health, disk guardrails, and graceful
   article-pipeline load shedding.**
4. **Implemented: isolated historical replay foundation.**
5. **Next implementation: close the remaining Step 7 replay, symmetry, outage,
   and multi-publisher acceptance gates.**
6. Build bounded regional activity baselines.
7. Generate evidence-linked world-change signals.
8. Deliver the read-only Jarvis map/timeline MVP.
9. Add grounded viewport briefings and non-delivering watchlists.
10. Harden the predictive engine and calibrate it in shadow.
11. Add explicitly opted-in delivery through Entity Core.
12. Complete system-wide replay, false-alert, licensing, security, retention,
    and workload promotion gates.

Maritime intelligence remains deferred until there is both a concrete operator
need and an approved, licensed provider.

## Prompt handoff contract

- Implementations 1, 1A, and 2 are live on schema 35 and have passed their
  initial drain, publisher-fairness, reserved-capacity, fresh-latency, workload,
  and disk-guardrail observations. Implementation 3 is implemented as an
  offline tool with no live migration or service integration. Implementation 4
  is implemented in schema 36, with its live drain/eligibility acceptance still
  open.
- The next implementation prompt means **Implementation 4A only**: accelerate
  capture and semantic assessment for evidence already attached to independent
  multi-publisher events, using only existing approved publisher-page policies
  and existing budgets. The prompt after that is a bounded live acceptance
  observation. If it produces a genuine comparison, Step 7 closes and the
  following planning prompt is Implementation 5.
- If implementation reveals a dependency that materially expands the scope,
  update this roadmap and call out the boundary change before doing that work.

## Implementation 1: fair scheduling and bounded acquisition

**Status:** implemented in migration 033 and the bounded acquisition/framing
pipeline; its live drain and publisher-fairness gates pass.

### Outcome

Every eligible publisher makes bounded progress, old semantic retries cannot be
starved by newly captured articles, worker restarts preserve rotation fairness,
and acquisition cannot add work beyond configured publisher and global queue
ceilings.  Existing queued work is preserved and drains normally.

### Storage and configuration

- Add migration `033_intelligence_scheduler_backpressure.sql` with a small
  durable scheduler-state table keyed by engine.  Store only the last completed
  rotation key and update time; do not store article text or model prompts in
  scheduler state.
- Add `IntelligenceStore` methods to read and advance scheduler state.  Updates
  must be transaction-safe and tolerate a publisher disappearing between
  selection and execution.
- Add bounded configuration for maximum active acquisition tasks per publisher
  and globally.  Active means `pending`, eligible or delayed `retry`, and
  `running`.  Use conservative defaults and clamp environment values.
- Document the new settings in `.env.example` and the main README.

### Semantic-framing scheduler

- Replace global newest-first selection with publisher round-robin selection.
- Begin each cycle after the durable publisher cursor and wrap once through the
  sorted eligible publisher set.
- Within each publisher, select work in this order:
  1. eligible `needs-model` retries, oldest assessment update first;
  2. captures whose content hash changed, oldest capture first;
  3. never-assessed captures, oldest capture first.
- Take at most one item per publisher per pass, then repeat passes only if batch
  and model-call capacity remains.
- Do not mark unattempted captures as `needs-model`.  A cooled budget lane must
  leave all unattempted work immediately eligible for the next cycle.
- Advance the durable cursor only after an item is actually attempted.  Engine
  reconstruction and process restart must not reset publisher preference.
- Preserve the publisher-blind prompt, literal-span validation, result cache,
  audit records, and shadow feature gates.

### Acquisition scheduler and backpressure

- Recover expired `running` leases as retries before selecting or enqueueing
  work.  Never reclaim an unexpired lease.
- Count active tasks by `documents.publisher_key`, falling back to `source_id`
  only when publisher identity is absent.
- Enqueue no more than the available slots under both the per-publisher and
  global ceilings.  Stop growth when an existing queue already exceeds a new
  ceiling; do not delete, cancel, or silently reprioritize existing tasks.
- Preserve publisher round-robin enqueueing, but query only enough candidates to
  fill currently available slots.
- Process eligible retries before new pending work within each publisher, oldest
  due retry first.  Round-robin publishers so one large queue cannot consume the
  whole processing batch.
- Respect each source contract's `article_requests_per_cycle` limit in addition
  to the new queue ceilings.
- A blocked task remains terminal unless a later explicit operator workflow
  changes its state.

### Store and audit surface

- Extend `article_analysis_overview()` with active task totals by publisher,
  oldest active-task time, and configured ceiling status.
- Expose enough state to distinguish `healthy`, `draining`, and
  `backpressure-active` without exposing captured article bodies.
- Keep raw scheduler state internal; dashboard/API consumers receive normalized
  health fields rather than implementation cursors.

### Tests

- Highly unequal publisher volumes still attempt every eligible publisher before
  any publisher receives a second item when capacity permits.
- An eligible old `needs-model` retry precedes a fresh capture for the same
  publisher.
- A publisher with retries cannot monopolize other publishers' batch slots.
- Cursor rotation survives constructing a new engine against the same store.
- A cooled model lane performs no call, writes no assessment, and does not move
  the cursor.
- Enqueueing fills only remaining publisher/global slots and enqueues nothing at
  either ceiling.
- A pre-existing queue above its ceiling is preserved and receives no new work.
- Expired running leases retry; live leases are untouched.
- Source request caps and host/policy protections continue to hold.
- Framing stays shadow-only and publisher factual assessments are unchanged.

### Completion gate

The focused tests and the full intelligence test suite pass.  A live observation
window shows that pending-task count is stable or declining, every enabled
publisher advances, old retries advance, and no additional factual-reputation
input is created.  Live observation may validate completion but must not be
encoded as a flaky wall-clock test.

### Explicitly out of scope

- Deleting or compacting the existing acquisition backlog.
- Article-retention deletion, database vacuuming, or destructive cleanup.
- Changing model budgets, prompts, framing dimensions, or factual credibility.
- Creating event comparisons without two genuinely assessed publishers.
- Historical replay, baselines, change signals, UI work, watchlists, forecasts,
  alerts, or maritime tracking.

### Expected files

- `agent/intelligence/migrations/033_intelligence_scheduler_backpressure.sql`
- `agent/intelligence/store.py`
- `agent/intelligence/article_acquisition.py`
- `agent/intelligence/framing.py`
- `agent/intelligence/config.py`
- `.env.example`
- `README.md`
- `tests/test_intelligence.py`

Changes outside this list require a concrete dependency discovered during
implementation and should be called out in the handoff.

## Implementation 1A: fresh-development fast path

**Status:** implemented and live in migration 034. The first observed fresh
publisher-page task was captured in two seconds and completed semantic framing
through the protected fresh lane in about 92 seconds while historical backfill
remained above its ceiling.

- Documents retrieved within 30 minutes receive a separate `fresh` work class.
- Fresh page acquisition has two reserved active slots per publisher and ten
  globally, independent of historical backfill ceilings.
- Processing remains publisher round-robin but selects fresh work before retries
  and backfill. Source-contract request limits still apply.
- Global reasoning capacity rises to 36 calls per hour and 300 per day.
- Historical article framing may use 8 calls per hour and 100 per day.
- The separate `article-fresh` lane may use 4 calls per hour and 40 per day, with
  2 hourly and 12 daily calls protected from other lanes.
- Semantic framing may make four calls per cycle and routes recent captures to
  the fresh lane. Publisher blindness, literal evidence spans, result auditing,
  and shadow-only behavior are unchanged.

**Live acceptance:** a newly collected eligible publisher-page article can be
enqueued while historical backfill remains over its ceiling, is selected in the
next bounded acquisition cycle, and reaches a framing attempt without waiting
for the backfill lane's hourly reset. Backfill must continue making progress and
fresh queues must remain within their independent ceilings.

## Implementation 2: workload health and graceful load shedding

This was the complete scope of Implementation 2.

**Status:** live on schema 35. The service reports `draining` below the disk
soft limit, with positive recent completion throughput and durable transition
state. All 151 intelligence/workload tests pass.

### Outcome

The service reports whether each bounded processor is keeping up, projects local
storage pressure, and pauses low-priority acquisition before resource exhaustion
while preserving already collected evidence and epistemic context.

### Migration and durable state

- Add `035_workload_health_and_load_shedding.sql`.
- Add `intelligence_workload_state`, keyed by engine, with current status,
  reason, bounded metrics JSON, policy version, first-entered time, last-checked
  time, and update time.
- Add append-only `intelligence_workload_transitions` with previous status, new
  status, reason, bounded metrics JSON, policy version, and transition time.
- Write a transition only when status or governing reason changes. Recomputing
  the same state or restarting the worker must not create duplicate transitions.
- Store no article bodies, prompts, credentials, provider payloads, or unbounded
  error strings in workload state.

### Configuration

- Add `ENTITY_WORKLOAD_HEALTH_WINDOW_MINUTES`, default `60`, bounded from 15
  minutes through 24 hours.
- Add `ENTITY_INTELLIGENCE_DISK_SOFT_LIMIT_BYTES`, default `2147483648` (2 GiB).
- Add `ENTITY_INTELLIGENCE_DISK_HARD_LIMIT_BYTES`, default `3221225472` (3 GiB).
- Require the hard limit to exceed the soft limit by at least 64 MiB after
  clamping. Invalid or reversed values fail closed to documented safe defaults.
- Disk usage means the combined byte size of the configured SQLite database,
  its `-wal` file, and its `-shm` file. Also report filesystem free bytes, but do
  not silently derive or change configured limits from free-space values.
- Document all values in `.env.example`, the README, and the engineering
  dashboard. The private `.env` may opt into different explicit limits, but the
  implementation must not guess a larger safe limit.

### Workload monitor

- Add `agent/intelligence/workload.py` with a small `WorkloadMonitor` owned by
  `IntelligenceWorker` and injected into `ArticleAcquisitionEngine`.
- Make file-size and clock readers injectable so threshold and time-window tests
  never need to fill a real disk or wait for wall-clock time.
- Refresh workload state before article acquisition and once at the end of a
  worker cycle. A monitor failure must not crash source collection or analysis.
- Use the following status precedence:

    1. `disk-hard-limit` when database-family bytes are at or above the hard limit;
    2. `disk-soft-limit` when bytes are at or above the soft limit;
    3. `unknown` when storage size or governing configuration cannot be read;
    4. `draining` when historical work exceeds a queue ceiling and recent
       completion throughput is positive;
    5. `backpressure-active` when a queue ceiling is reached without evidence of
       positive recent drain;
    6. `healthy` otherwise.
- Report missing data as `unknown`; never convert missing rows, an unreadable
  file, or a zero-length observation window into healthy state.

### Load-shedding policy

- `healthy`, `draining`, and `backpressure-active` retain the scheduler behavior
  already delivered by migrations 033 and 034.
- At `disk-soft-limit`:

    - do not enqueue historical article tasks;
    - do not fetch pending historical publisher pages;
    - continue the separately bounded fresh-development enqueue and fetch path;
    - continue semantic analysis of existing captures, deterministic event work,
      forecast resolution, and audit writes.

- At `disk-hard-limit`:

    - do not enqueue or fetch either historical or fresh publisher pages;
    - leave queued tasks unchanged and leases unclaimed;
    - continue bounded semantic analysis of already captured text, deterministic
      event work, forecast resolution, and required audit/state writes.

- At `unknown`, use the soft-limit behavior: pause historical page growth while
  preserving the bounded fresh path and explicitly reporting uncertainty.
- Blocked tasks remain terminal. No workload state may delete, cancel, complete,
  reprioritize, or rewrite an acquisition task.
- This slice governs the article/full-text pipeline only. System-wide connector,
  media, environmental-layer, and backup retention enforcement remains Step 16
  work and must not be implied by an article-pipeline health label.

### Store metrics and API

- Add `IntelligenceStore.workload_health(window_minutes=60)` with bounded,
  read-only results containing:

    - current status, reason, policy version, entered time, and checked time;
    - database, WAL, SHM, combined, configured-limit, and filesystem-free bytes;
    - active counts by work class, status, and publisher;
    - oldest and median active-task age;
    - enqueue, completion, capture, assessment, retry, blocked, and expired-lease
      counts over the configured recent window;
    - observed per-publisher completion rate and a clearly labeled drain estimate,
      or `unknown` when throughput is zero or the sample is inadequate;
    - bounded recent fresh-development retrieval-to-capture,
      capture-to-assessment, and end-to-end p50/p95 latency;
    - recent durable workload transitions.
- Calculate medians and percentiles deterministically from a bounded indexed
  sample. Do not load the entire task or capture history into memory.
- Add `GET /api/intelligence/workload-health`. Clamp its optional window and
  transition limits and expose no article bodies, prompts, secrets, or private
  filesystem paths.
- Keep `article_analysis_overview()` backward compatible; it may link or repeat
  the normalized current status but must not remove existing response fields.

### Engineering dashboard

- Add a compact workload card to the existing engineering/epistemic health
  surface, not the future Jarvis product.
- Show current status, combined database size versus soft/hard limits, historical
  and fresh queue counts, oldest/median age, recent completion rate, drain
  estimate, and fresh p50/p95 latency.
- Use distinct warning/error styling for soft, hard, and unknown states. State
  exactly which article work is paused; do not label the entire intelligence
  service unhealthy when only historical page capture is shed.
- Show the latest bounded transitions for audit. Do not add mutation controls,
  cleanup buttons, limit editors, or remote actions.

### Tests

- Migration 035 applies once, preserves migration 034 tasks, and defaults all
  existing work to its existing work class.
- Database/WAL/SHM sizes sum correctly; missing WAL/SHM count as zero while an
  unreadable database path produces `unknown`.
- Exact boundary values enter soft and hard states deterministically.
- Reversed, negative, and too-close limits resolve to safe documented values.
- Restarting or refreshing an unchanged state writes no duplicate transition.
- Queue status, oldest/median age, throughput, drain estimate, and unknown-rate
  behavior are fixture-backed.
- Fresh p50/p95 latencies reproduce from known timestamps and remain bounded in
  query size.
- Soft state blocks historical enqueue and page fetch while allowing bounded
  fresh capture and existing semantic analysis.
- Hard state blocks all page enqueue/fetch, leaves tasks unchanged, and still
  permits analysis of an existing capture and forecast-resolution/audit work.
- Unknown state uses soft behavior and is displayed as unknown.
- Source-contract request caps, publisher rotation, fresh reserved capacity,
  budget isolation, and factual-credibility separation continue to pass.
- API and dashboard contract tests prove that no article text, prompt, secret,
  or private absolute path is returned.

### Expected files

- `agent/intelligence/migrations/035_workload_health_and_load_shedding.sql`
- `agent/intelligence/workload.py`
- `agent/intelligence/store.py`
- `agent/intelligence/config.py`
- `agent/intelligence/worker.py`
- `agent/intelligence/article_acquisition.py`
- `agent/intelligence/web.py`
- `intelligence_dashboard/app.js`
- dashboard HTML/CSS only if the existing health surface cannot host the card
- `.env.example`
- `README.md`
- `tests/test_intelligence.py`

Changes outside this list require a concrete dependency discovered during
implementation and must be called out before expanding scope.

### Explicitly out of scope

- Automatic deletion, `VACUUM`, database replacement, or retention enforcement.
- System-wide suspension of compact source-document polling.
- Media-file, environmental-layer, backup, or log retention.
- Historical replay or changes to analytical results.
- External health notifications.
- Baselines, signals, Jarvis UI, watchlists, forecast promotion, or alerts.

### Completion gate

Focused tests and the complete intelligence suite pass. After restart, schema 35
is active, the current approximately 1.1 GiB database reports below the default
soft limit, the historical queue continues draining, and a synthetic injected
size-reader test—not real disk filling—has proven soft/hard behavior. Queue and
disk pressure are visible and reproducible, overload stops the documented page
growth before exhaustion, existing evidence continues through safe bounded
analysis, and no data is deleted.

## Implementation 3: isolated replay foundation

**Status:** implemented and validated as an offline tool. All six fixtures
reproduce in isolated temporary databases, the bounded live-database reader is
read-only, and all 160 intelligence/workload/replay tests pass.

### Outcome

Add a deterministic, cutoff-safe replay harness that reconstructs a bounded
subset of the intelligence pipeline from ordered immutable evidence in a fresh
temporary database. Every run freezes its input, source policies, algorithm
versions, clock, model fixtures, and configuration in a canonical manifest.
Repeating the same run produces the same normalized result fingerprint, while
the source and live databases remain untouched.

This implementation builds replay infrastructure and the first fixture corpus.
It does not use replay results to change production event matching or close the
remaining Step 7 acceptance gate; that is the following implementation.

### Isolation and safety boundary

- Add no live-database migration. Replay metadata belongs in the temporary run
  directory and replay database, not in production tables.
- Create every replay database under a new `TemporaryDirectory` by default and
  initialize it through the normal `IntelligenceStore` migrations. Never use a
  supplied source database as the destination.
- Resolve and compare source, destination, WAL, and SHM paths before writing.
  Reject equality, aliases, symlink collisions, the repository root, home
  directory, or an existing non-replay destination.
- Read a database source through a SQLite read-only connection with
  `PRAGMA query_only=ON` and a consistent read transaction. Fixture bundles are
  read-only inputs as well.
- Do not run connectors, publisher-page acquisition, media download, geocoding,
  external models, forecast generation, notifications, or any network request.
- A replay run may write only inside its temporary/output run directory. It may
  never update source cursors, scheduler state, budgets, workload state, source
  health, or any other live state.
- The CLI defaults to ephemeral output. An explicit output directory may retain
  the replay database, manifest, and summary, but must pass the same path-safety
  checks and contain no credentials or private source path.
- Prove non-mutation against a quiescent fixture database by hashing the
  database, WAL, and SHM family before and after replay. For a running live
  database, guarantee non-mutation structurally through read-only access rather
  than claiming byte stability while the service itself may write.

### Replay input contract

- Add a versioned `replay-bundle-v1` schema. A bundle contains:

  - a stable fixture/bundle key and evidence cutoff;
  - source identities and the exact source-policy snapshots used by the run;
  - ordered document versions with original source identity, external identity,
    publication time, capture time, status, metadata, reporting-family fields,
    and content hashes;
  - optional retained article captures with capture time, extractor, policy
    version, content hash, and bounded normalized text;
  - optional frozen deterministic/model responses keyed by method, version, and
    input hash;
  - explicit expected gaps such as source-down intervals or no-event windows;
  - schema version, bundle hash, and fixture provenance.

- For database-backed input, export only immutable source evidence at or before
  the cutoff from `sources`, `source_policies`, `documents`,
  `document_versions`, and eligible `article_content_captures`. Do not import
  situations, claims, events, fusion decisions, framing assessments,
  comparisons, forecasts, reputations, scheduler cursors, reasoning attempts,
  workload state, or other derived/live state.
- Treat policy snapshots as replay inputs. The current `source_policies` row may
  supply a snapshot only when its recorded policy version matches the requested
  run contract. Missing or mismatched historical policy state fails closed; the
  runner must not pretend the current policy was valid at an earlier cutoff.
- Order evidence by normalized capture time, then source ID, external ID,
  document-version number, and content hash. This total order is part of the
  manifest and resolves equal timestamps deterministically.
- Exclude every version, article capture, policy input, and frozen response after
  the requested cutoff. Later corrections may not leak backward.
- Validate bundle structure, hashes, timestamps, source references, maximum
  item count, per-item bytes, and aggregate bytes before creating the replay
  database. Unknown fields are rejected for the versioned fixture format.

### Deterministic execution contract

- Add `agent/intelligence/replay.py` with `ReplayRunner`, `ReplayClock`,
  `ReplayBundle`, and a small stage registry. The runner advances its logical
  clock to each ordered capture and runs configured bounded stages to quiescence
  before advancing past the applicable cutoff.
- Make clock access injectable in the store and only the processors exercised by
  this replay slice. Replace SQL `julianday('now')` in those paths with bound
  replay timestamps. Production constructors continue to use the existing UTC
  wall clock by default.
- Make new document identity injectable. Production continues using UUID4;
  replay uses a stable hash/UUID5 derived from the bundle key, canonical source
  identity, external identity, and first-version hash. SQLite surrogate IDs are
  stabilized by the total insertion order.
- Centralize the replayed algorithm contract in a read-only version registry.
  The first registry includes source-contract, claim extraction, world-graph,
  event-fusion feature/method, semantic-framing, event-framing-comparison, and
  canonical-event-assessment versions actually invoked by the run.
- Fail closed when a requested method/version is absent, a fixture model result
  is missing, or code versions differ from the manifest. Never fall back to a
  live model or silently substitute the newest algorithm.
- Use a frozen router that returns only bundle responses keyed by method,
  version, and input hash. Record response hashes and validation outcomes but no
  prompts or provider payloads in the manifest.
- Initially replay only the bounded Step 7 path needed for later acceptance:
  immutable document ingestion, supplied full-text capture, deterministic
  document projection/features required by event correlation, world-graph
  projection, event fusion, frozen semantic framing, event-level framing
  comparison, and canonical event assessment.
- Do not replay publisher-page fetching. Article captures in a bundle represent
  evidence that had already been retained by the cutoff.
- Stage execution must use explicit batch bounds and terminate on quiescence or
  a configured maximum pass count. A non-quiescent stage fails the run with a
  bounded diagnostic instead of looping indefinitely.

### Canonical manifest and result summary

- Emit `manifest.json` using sorted keys and canonical JSON encoding. Its stable
  portion contains:

  - manifest schema and runner version;
  - deterministic run ID derived from the canonical input contract;
  - bundle hash, cutoff, ordered evidence hash, and evidence counts;
  - exact source-policy snapshots or their hashes;
  - algorithm/method versions and replay configuration;
  - logical clock start/end and stage/pass counts;
  - frozen-response-set hash;
  - normalized result fingerprint and completion status.

- Keep operational wall-clock start/end, temporary paths, host details, process
  IDs, and random values outside the stable fingerprint. Do not expose a private
  absolute source path in either output.
- Emit `summary.json` with bounded counts and normalized signatures for
  documents/versions, reporting families, projected observations, canonical
  events, memberships, fusion outcomes/reviews, framing assessments, literal
  evidence spans, comparisons, and epistemic assessments.
- Normalize away SQLite row IDs and incidental timestamps when computing the
  result fingerprint. Preserve stable source/document keys, evidence hashes,
  method versions, cutoffs, relationship types, and decision components so a
  meaningful algorithm change changes the fingerprint.
- Store no full article text, model prompt, credentials, raw provider response,
  or unbounded error in either manifest or summary. Retained replay text remains
  only inside the isolated replay database and input fixture where test policy
  permits it.
- A failed run emits a bounded failure code and the validated portion of the
  manifest, but never labels partial results successful.

### Initial fixture corpus

- Add small synthetic, licensed-for-tests bundles under
  `tests/fixtures/intelligence_replay/`. No fixture may copy a real article or
  contain a real credential, private channel, mailbox content, or user data.
- Cover these structural scenarios:

  1. **Publisher imbalance:** three publishers report one event at sharply
     unequal volumes; total capture order is stable and repetition cannot erase
     the low-volume publisher.
  2. **Source outage:** one publisher has an explicit coverage gap; absence is
     retained as unknown coverage and is not converted to factual calm or
     selection-framing evidence.
  3. **Correction:** a later immutable document version corrects an earlier
     report; a pre-correction cutoff cannot see it and a later cutoff preserves
     both versions and the supersession trail.
  4. **Syndication:** copied reports share a reporting family and cannot inflate
     independent-source counts.
  5. **Duplicate evidence:** exact duplicate versions are idempotent and do not
     create duplicate observations, memberships, or comparisons.
  6. **No-event period:** an explicit time window with adequate/unknown coverage
     produces no invented event, comparison, or factual assertion.

- Each fixture includes frozen framing responses with literal spans when model
  behavior is required. Publisher identity must not appear in the frozen
  framing request key or response-selection logic.
- This slice proves that the harness represents and reproduces these scenarios.
  The following Step 7 implementation will add the full symmetry/outage scoring
  matrix and may fix production linkage based on replay findings.

### Configuration and CLI

- Provide a local command such as
  `python -m agent.intelligence.replay --fixture <key>` and an explicit bounded
  database-source mode requiring a cutoff and selection filter.
- Add conservative clamped settings for maximum evidence items, maximum bundle
  bytes, stage batch size, and maximum stage passes. Test defaults remain small;
  no unlimited value is accepted.
- Require an explicit document/source/time selection for database-backed replay.
  Reject an unbounded request to replay the entire live database in this slice.
- Print only the run status, deterministic run ID, cutoff, counts, result
  fingerprint, and retained output location when requested. Never print article
  bodies, frozen model payloads, credentials, or private source paths.

### Store and API boundary

- Add narrowly scoped store helpers for replay import, clock/identity injection,
  and normalized result export. Normal ingestion signatures and production
  behavior remain backward compatible.
- Replay is an offline engineering tool. Add no worker scheduling, web API,
  dashboard control, background replay, or remote trigger.
- Do not write replay-run rows to the live database. A later Step 15 evaluation
  store may persist promotion reports after its retention and privacy contract
  is designed.

### Tests

- Replaying the same bundle twice produces identical stable manifests and result
  fingerprints, even in different temporary directories and at different wall
  times.
- Evidence with identical capture timestamps follows the documented tie-break
  order. Changing that order, cutoff, policy snapshot, algorithm version, or
  frozen response changes the run ID or fails validation as appropriate.
- Pre- and post-correction cutoffs prove that future versions and derived state
  cannot leak backward.
- The six initial fixtures reproduce their structural expectations and remain
  bounded in item count, bytes, passes, and output size.
- A missing policy snapshot, version mismatch, invalid hash, malformed
  timestamp, missing frozen response, unknown fixture field, or non-quiescent
  stage fails closed with a bounded error code.
- Tests patch network and live model entry points to raise, proving replay makes
  no outbound request and has no live-model fallback.
- Source connections reject writes. A quiescent source database plus WAL/SHM
  family has identical hashes and row counts before and after successful and
  failed runs.
- Destination/source path alias, symlink, repository-root, home-directory, and
  existing-output cases are rejected before mutation.
- Production store and engine constructors retain wall-clock and UUID4 behavior
  when replay dependencies are not supplied.
- Manifest and summary contract tests prove they contain no article text,
  prompt, credential, provider payload, private absolute path, or unbounded
  error.
- Existing scheduler fairness, retry priority, fresh capacity, budget isolation,
  workload shedding, event fusion, framing, factual-credibility separation, and
  all intelligence tests continue to pass.

### Expected files

- `agent/intelligence/replay.py`
- `agent/intelligence/replay_manifest.py` if canonicalization is clearer as a
  separate module
- `agent/intelligence/store.py`
- replayed engine files only where clock injection is required
- `agent/intelligence/config.py`
- `tests/test_replay.py`
- `tests/fixtures/intelligence_replay/*.json`
- `.env.example`
- `README.md`
- `docs/world-intelligence-execution-roadmap.md`

No migration, worker, service, web API, dashboard, connector, retention, or
notification file should change unless implementation discovers a concrete
dependency and records the boundary change here first.

### Explicitly out of scope

- Replaying the entire live corpus or running replay automatically.
- Network acquisition, external model calls, geocoding, media processing, or
  forecast generation/resolution.
- Fixing production event linkage or manufacturing a cross-publisher comparison.
- Declaring the six fixture scenarios sufficient to close corrective Step 7.
- Changing factual publisher credibility, framing status, production budgets,
  scheduler behavior, workload limits, or source policies.
- Persisting replay reports in the live database.
- Regional baselines, change signals, Jarvis UI, watchlists, alerts, forecast
  promotion, retention deletion, `VACUUM`, or system-wide Step 16 enforcement.

### Completion gate

Focused replay tests and the complete intelligence suite pass. Two runs of every
fixture in separate temporary directories produce identical stable manifests
and normalized result fingerprints. Cutoff, correction, syndication, duplicate,
outage, imbalance, and no-event behavior is reproducible; no network/model
fallback occurs; source database-family hashes remain unchanged in quiescent
tests; production defaults remain unchanged; and no replay artifact enters the
live database or dashboard.

## Implementation 4: close corrective Step 7 with replay evidence

**Status:** implemented on schema 36; focused replay and compatibility tests
pass. The first bounded live acceptance window drained all 53 assessed
documents through projection and all 53 assessed observations through fusion
v3. Across two observed v3 cycles, processed work rose from 200 to 300 while
the eligible general backlog fell from 26,615 to 26,530 and its oldest timestamp
advanced, despite ongoing ingestion. No threshold was lowered and no event was
force-linked.

Step 7 remains open for an evidence-based reason: the live corpus has zero
events with two assessed publishers and therefore zero eligible v2 comparisons.
Eight events have multiple publisher memberships, but none currently has two
complete assessed publisher captures; the readiness audit reports the capture
gate. Implementation 5 remains blocked until normal acquisition and assessment
produce a genuinely eligible event and the append-only shadow comparison is
observed. This is a pipeline-coverage finding, not a conclusion about any
publisher.

### Observed failure state

The schema-35 live audit after Implementation 3 found that zero comparisons are
not explained only by insufficient semantic assessments:

- 39 captures currently have `complete` framing assessments, representing 37
  documents across all three enabled publishers.
- Only 14 of those documents have a world-graph observation and only 13 have an
  active canonical-event membership. Twenty-three assessed documents have not
  reached world-graph projection.
- 24,242 world-event observations have no v2 fusion decision. World graph can
  materialize roughly 80 historical observations per cycle while fusion's
  recent escape path selects only 20 observations that fall behind its advanced
  document-version cursor. The backlog can therefore grow even while both
  processors report progress.
- The v2 fusion cursor was near the newest document version while world-graph
  historical projection was far behind it. Observations created later for an
  older document version are permanently behind the v2 historical cursor and
  depend on the undersized recent escape path.
- Legacy observations already assigned by fusion v1 can be reprocessed by v2
  with their own current event in the candidate set. A high self-score then
  records a v2 `link` back to the same event instead of evaluating genuine peer
  events. The live Aramco example exhibited this exact behavior.
- Every event containing a completed assessed article currently has only one
  assessed publisher, so the comparison engine correctly emits no comparison.
- The clean `publisher_imbalance` replay fixture produces five memberships in
  one event, three publisher assessments, and one comparison. This establishes
  that the clean-path fusion and comparison contracts work; the corrective work
  must target scheduler alignment and legacy reconciliation rather than lower
  global thresholds or bypass eligibility.

These counts are an audit snapshot, not hard-coded acceptance values. Tests must
reproduce the failure structures with synthetic evidence rather than depend on
the changing live database.

### Outcome

Make comparison-ready assessed documents progress through world-graph and event
fusion without starvation, replace cursor-trapped v2 backfill with an
idempotent unprocessed-work scheduler, reconcile legacy self-memberships under a
new append-only fusion version, and run event comparisons only for genuinely
eligible independent multi-publisher events.

The implementation closes corrective Step 7 only if the replay matrix passes
and a live observation window produces at least one genuine eligible
multi-publisher event comparison. If no such real event exists after the
pipeline is current, the system must remain at zero comparisons, report the
eligibility gap, and leave Step 7 open rather than manufacture one.

### Migration and version boundary

- Add `036_step7_replay_closure.sql` containing only indexes/state needed for
  bounded readiness scheduling and audit queries. Do not rewrite existing
  observations, decisions, memberships, events, assessments, or comparisons in
  the migration.
- Add a covering/indexed path for fusion's `NOT EXISTS` lookup by observation
  and method, observation capture ordering, assessment/capture/document
  readiness joins, and eligible comparison lookup where SQLite requires it.
- Advance event fusion to `deterministic-event-fusion-v3` and its feature
  contract to `event-fusion-features-v3`. Preserve all v1/v2 decisions and
  membership history append-only.
- Advance event comparison to `event-framing-comparison-v2`. Preserve v1
  comparisons; never update or delete them to make v2 appear successful.
- Use separate durable scheduler lane names for v3 work. A restart must resume
  the same readiness/backfill policy without treating a cursor as evidence that
  all older observations were processed.
- Keep world-graph projection method and semantic-framing v2 unchanged unless a
  replay test proves an actual semantic defect. Scheduler changes alone do not
  justify rewriting immutable projection records.

### World-graph comparison-readiness path

- Reserve a bounded portion of each existing world-graph document batch for
  documents that have a complete semantic-framing assessment but no
  `world_event_observation` for the assessed document version.
- Select readiness work publisher round-robin with a durable rotation cursor.
  One publisher cannot consume the readiness reserve before every other
  eligible publisher receives a slot.
- Within a publisher, process the oldest assessed capture/document version
  first. Corrections retain version order and later versions cannot replace
  earlier evidence at a prior cutoff.
- Advance the readiness cursor only after projection is actually attempted.
  Restart, a cooled model budget, or an unrelated engine failure cannot mark an
  assessed document projected.
- Preserve bounded capacity for ordinary recent and historical world-graph work;
  comparison readiness is a reserve, not permission to starve authoritative
  observations or the general backfill.
- Replace reliance on `version_id > historical_cursor` as the sole completeness
  condition. Missing projections must remain discoverable through an indexed
  `NOT EXISTS` path even when their document version is behind the cursor.
- Continue excluding private mail, prediction markets, forecasts, and reference
  layers from report-event projection under the existing evidence-role rules.

### Fusion v3 scheduler

- Select only observations without a v3 decision. Do not use the maximum
  document-version cursor to declare older observations complete.
- Divide each bounded batch into:

  1. a publisher-fair reserve for observations whose documents have complete
     framing assessments and are therefore comparison-ready;
  2. oldest unprocessed observations by capture time and stable observation ID;
  3. a small recent reserve so genuine new developments retain low latency.

- Deduplicate observations selected through more than one class before
  processing. Every class remains bounded and the total never exceeds the
  configured fusion batch size.
- Persist only rotation/cadence state, not article text, prompts, candidate
  payloads, or a cursor that can hide unprocessed work.
- Expose counts and oldest ages for comparison-ready, ordinary historical, and
  recent v3 work so positive throughput cannot conceal a growing older backlog.

### Legacy-membership reconciliation

- When an observation already has an active membership from v1/v2, exclude that
  current event from alternate-candidate scoring. Otherwise the observation's
  own title, time, location, and identifiers can dominate its candidate score.
- Distinguish these outcomes explicitly:

  - `retain`: no alternate event clears the link/review threshold, so the
    current membership remains active;
  - `link`: a different event clears the auto-link threshold and receives the
    observation through a new v3 membership;
  - `review`: a different event clears only the review threshold; the current
    membership remains active until an operator resolves the review;
  - `create`: only an observation with no valid current membership seeds a new
    event.

- A `retain` decision is an audit outcome, not a new membership. It must not
  deactivate/reinsert the same event membership or create a misleading link.
- On a v3 move, append the new membership, close the prior active membership,
  and recompute/version both the source and target events. Preserve the exact
  decision, score components, vetoes, cutoff, feature version, and reason.
- If the source event becomes empty, use the existing reversible alias/merge
  audit semantics. Do not delete it. If other observations remain, recompute it
  without silently moving them.
- Candidate ordering and tie-breaking remain deterministic and publisher blind.
  Publisher identity, framing score, and factual credibility cannot be fusion
  features.
- Do not lower the current auto-link or review thresholds globally in this
  implementation. Any later threshold change requires a separate replay report
  showing merge/split tradeoffs and hard-negative performance.

### Comparison v2 eligibility and scheduling

- Query events through an indexed eligibility predicate rather than repeatedly
  scanning only the newest active events.
- An eligible event requires:

  - at least two active member documents from distinct publisher keys;
  - complete, literal-span-validated framing assessments for at least two of
    those publishers;
  - at least two independent reporting families after falling back to publisher
    identity only when family lineage is absent;
  - retained captures and memberships at or before the comparison evidence
    cutoff;
  - no source-health/acquisition-coverage condition that makes the requested
    selection-framing dimension unknowable.

- Copied/syndicated reports may remain visible in the event evidence but cannot
  satisfy the independent-peer gate by repetition.
- Build v2 input hashes from stable content hashes, publisher/family keys,
  framing vectors, membership/version hashes, method versions, and the evidence
  cutoff—not SQLite surrogate capture IDs or wall-clock execution time.
- Derive the evidence cutoff from the latest included immutable evidence. Later
  captures or corrections produce a new append-only comparison input hash; they
  never rewrite the earlier comparison.
- Select the oldest eligible event lacking its current v2 input hash first, with
  deterministic event-ID tie-breaking. A stream of newer ineligible events
  cannot starve an older eligible event.
- Keep comparison status `shadow`. Shared/divergent factual claims remain empty
  unless supported by the existing claim/evidence pipeline; vector differences
  alone cannot be narrated as factual disagreement or publisher motive.
- Selection framing stays `unknown` when outage, source health, acquisition
  coverage, peer coverage, or independent-family support is inadequate.

### Readiness metrics and engineering audit

- Add a bounded `IntelligenceStore.comparison_readiness()` result containing:

  - complete assessments and distinct assessed documents by publisher;
  - assessed documents awaiting projection;
  - assessed observations awaiting a v3 fusion decision;
  - assessed observations with `retain`, `link`, `review`, or `create` outcomes;
  - active events grouped by zero, one, or multiple assessed publishers;
  - events blocked by publisher, independent-family, capture, health, or
    coverage gates;
  - currently eligible events and current v2 comparisons;
  - oldest/median age and recent completion throughput for readiness projection
    and fusion;
  - v3 backlog counts by class and publisher;
  - bounded latest decisions/comparisons using hashes and titles only where the
    existing article excerpt/display policy permits them.

- Extend `article_analysis_overview()` without removing or changing existing
  fields. It may include a compact normalized comparison-readiness summary.
- Add `GET /api/intelligence/comparison-readiness` with clamped window and row
  limits. Return no article body, evidence span beyond existing display policy,
  prompt, credential, provider payload, scheduler cursor, or private path.
- Add a compact engineering/epistemic-health card showing the projection queue,
  v3 fusion queue, eligible-event count, comparison count, oldest ages, recent
  throughput, and the specific current gate. Do not add mutation, merge,
  threshold, replay, or promotion controls.

### Configuration

- Add conservative bounded reserves, clamped to their parent batch sizes:

  - `ENTITY_WORLD_GRAPH_COMPARISON_READY_PER_CYCLE`, default `20`;
  - `ENTITY_EVENT_FUSION_COMPARISON_READY_PER_CYCLE`, default `20`;
  - `ENTITY_EVENT_FUSION_RECENT_PER_CYCLE`, default `20`.

- The remaining fusion capacity serves oldest unprocessed work. A reserve of
  zero is permitted for controlled tests, but invalid values fall back safely
  and no configuration may increase the parent batch limit.
- Document that these settings prioritize already assessed evidence through
  deterministic projection/fusion; they do not increase model budgets, network
  acquisition, or factual weight.

### Replay and fixture matrix

- Update the replay algorithm registry for fusion v3 and comparison v2. Prior
  manifests retain their recorded v2/v1 versions and remain interpretable.
- Extend synthetic fixtures/tests to cover:

  1. **Cursor inversion:** an old document is projected after fusion has already
     processed newer versions; v3 still finds and processes it.
  2. **Legacy self-link:** an observation begins in a v1 event; v3 excludes that
     event from alternate scoring and records `retain` or links to a genuine
     peer rather than self-linking.
  3. **Publisher imbalance:** low-volume publishers reach projection, fusion,
     and comparison before a high-volume publisher receives repeat reserved
     slots.
  4. **Publisher-blind symmetry:** swapping publisher labels/arrival order while
     preserving evidence produces an isomorphic event/comparison result after
     publisher-key normalization.
  5. **Outage:** missing peer coverage remains unknown and creates no selection
     framing conclusion.
  6. **Correction/cutoff:** a pre-correction run cannot see the later version;
     the later run appends a new result and preserves the earlier one.
  7. **Syndication:** two publisher labels in one reporting family do not pass
     the independent-peer gate.
  8. **Duplicate evidence:** retries/restarts write one v3 decision per
     observation/method/candidate contract and no duplicate active membership.
  9. **Hard negatives:** similar vocabulary, nearby unrelated incidents, and
     same-day regional stories do not merge merely to create a comparison.

- Run every matrix case twice in different temporary directories and compare
  normalized result fingerprints. Candidate query order may not change the
  result.
- Assert before/after that publisher factual credibility, topic reliability,
  source policies, semantic assessments, literal evidence, and immutable source
  versions are unchanged by fusion/comparison replay.

### Tests

- Migration 036 applies once and preserves every v1/v2 decision, membership,
  event version, comparison, capture, and assessment.
- Assessed documents behind the world-graph cursor enter the readiness reserve;
  publisher rotation and oldest-first order survive engine reconstruction.
- World graph continues ordinary recent/historical progress when readiness work
  is continuously available.
- Observations created behind the old fusion cursor receive v3 decisions; the
  oldest v3 backlog declines under sustained input instead of being hidden.
- A legacy self-event is never scored as its own alternate link candidate.
  `retain`, `link`, `review`, and `create` have distinct audited state effects.
- Re-linking recomputes both affected events, leaves one active membership, and
  preserves reversible history. Restart/retry is idempotent.
- Comparison v2 skips single-publisher, dependent-family, incomplete-framing,
  unhealthy-source, inadequate-coverage, and post-cutoff evidence cases with an
  explicit readiness reason.
- An eligible independent multi-publisher event receives one comparison per
  stable input hash. Re-running unchanged evidence creates none; a later valid
  correction appends rather than overwrites.
- Comparison input hashes reproduce across replay databases with different
  surrogate IDs and wall-clock times.
- Symmetry, outage, correction, syndication, duplicate, imbalance, cursor
  inversion, self-link, and hard-negative replay fixtures pass twice.
- Source-contract limits, scheduler fairness, fresh-development latency,
  workload shedding, model-budget isolation, literal-span validation, cutoff
  safety, and factual/framing separation continue to pass.
- API/dashboard contracts expose bounded readiness metadata and no captured
  article text, prompt, credential, private path, or mutation control.
- The full intelligence, workload, and replay suites pass.

### Expected files

- `agent/intelligence/migrations/036_step7_replay_closure.sql`
- `agent/intelligence/world_graph.py`
- `agent/intelligence/event_fusion.py`
- `agent/intelligence/framing.py`
- `agent/intelligence/store.py`
- `agent/intelligence/config.py`
- `agent/intelligence/replay.py`
- `agent/intelligence/web.py`
- `intelligence_dashboard/app.js`
- `.env.example`
- `README.md`
- `tests/test_intelligence.py`
- `tests/test_replay.py`
- `tests/fixtures/intelligence_replay/*.json`
- `docs/world-intelligence-execution-roadmap.md`

Changes outside this list require a concrete dependency discovered during
implementation and a roadmap boundary update before expansion.

### Explicitly out of scope

- Manufacturing, manually merging, or force-linking a live event so a
  comparison exists.
- Globally lowering fusion thresholds or removing hard vetoes without a separate
  evaluated replay report.
- New semantic-framing dimensions, prompt changes, model-budget increases,
  publisher scoring, ideology labels, motive inference, or factual-credibility
  changes.
- Promoting article capture, semantic framing, event comparison, or selection
  framing out of shadow.
- Deleting or rewriting v1/v2 decisions, memberships, event versions,
  comparisons, captures, assessments, or source evidence.
- Automatic review resolution, bulk event merge/split, or operator mutation UI.
- New connectors, publisher-page acquisition changes, retention deletion,
  `VACUUM`, or system-wide load shedding.
- Regional baselines, change signals, Jarvis product UI, watchlists, alerts,
  forecast promotion, or maritime intelligence.

### Completion gate

Migration 036 and focused/full tests pass. Replay proves cursor inversion and
legacy self-link correction without increasing hard-negative merges; assessed
documents and observations make publisher-fair bounded progress through both
readiness stages; old v3 work declines under load; comparison v2 is
cutoff-stable and independent-family-aware; and factual credibility is
unchanged.

During a bounded live observation window, the readiness audit must show the
projection and v3 fusion queues draining. At least one genuinely eligible real
event with two independently assessed publishers must produce an append-only
shadow comparison before corrective Step 7 is marked complete. If the corpus
contains no such event, zero remains the correct result, the blocking gate is
reported explicitly, and this implementation remains open rather than weakening
evidence standards.

## Implementation 4A: event-aware comparison coverage

**Status:** implemented and deployed on schema 36. All 279 tests pass, including
event-ready end-to-end comparison, deterministic pressure replay, feed-only
policy exclusion, fresh-capacity, workload, and dashboard contracts. Live
configuration has two acquisition and two framing reserve slots per cycle. The
separate bounded live acceptance is now pending; its initial gate is one viable
event awaiting approved Al Jazeera enqueue alongside an already assessed NPR
peer, while seven other multi-publisher events are policy-ineligible.

### Why this corrective slice exists

Implementation 4 fixed projection and fusion starvation. In the first schema-36
live window, all 53 assessed documents reached projection and all 53 assessed
observations received v3 decisions. General v3 work also declined across
successive cycles. The remaining comparison gate is upstream coverage, not
fusion or comparison logic:

- Eight live events have active memberships from at least two publisher keys.
- None has complete semantic assessments from two publishers.
- Seven events currently depend on a peer configured `feed-only` or on social
  signals that are not eligible for publisher-page acquisition.
- One event has an immediately viable, already-approved path: NPR has a complete
  541-word capture awaiting framing, while associated Al Jazeera documents are
  eligible under the existing `publisher-page` policy but have not been queued.
- The current acquisition and framing schedulers are publisher-fair globally,
  but they do not reserve capacity for documents that can complete an otherwise
  valid independent multi-publisher event. Large ordinary backlogs can therefore
  delay the only evidence capable of satisfying the comparison gate.

This implementation prioritizes existing eligible work. It does not authorize
capture from any new publisher, manufacture event linkage, or relax comparison
eligibility.

### Outcome

Add a small, bounded event-readiness reserve to article acquisition and semantic
framing so an already-linked multi-publisher event can progress from missing
capture to complete literal-span assessment without being starved by unrelated
backfill. Preserve all current caps, retries, freshness guarantees, source
policies, evidence boundaries, and shadow-only comparison behavior.

The implementation succeeds technically when event-ready work advances
deterministically without starving ordinary or fresh work. Corrective Step 7
closes only after the following live observation produces at least one genuine
comparison from two independent assessed publishers. Zero remains correct when
the evidence does not satisfy that gate.

### Schema and method boundary

- Reuse schema 36 and `intelligence_scheduler_state` unless `EXPLAIN QUERY PLAN`
  demonstrates that a narrowly scoped index is required. If so, add migration
  `037_event_ready_coverage.sql` containing indexes only.
- Do not add article text, prompt payloads, event IDs, or candidate payloads to
  scheduler state. Persist only rotation keys needed for deterministic fairness.
- Keep `article-acquisition-v1`, `semantic-framing-v2`,
  `deterministic-event-fusion-v3`, and `event-framing-comparison-v2` unchanged.
  Scheduling priority does not change immutable evidence semantics.
- Preserve all existing tasks, captures, assessments, observations, decisions,
  memberships, event versions, and comparisons append-only.

### Event-ready eligibility

A document version is event-ready only when all of the following are true:

- its observation has an active membership in an active canonical event;
- that event has active member documents from at least two distinct publisher
  keys and at least two independent reporting families;
- the event has fewer than two publishers with complete semantic assessments;
- advancing this document can fill a missing publisher slot rather than repeat
  an already assessed publisher;
- the source is healthy and the evidence is within the current retention and
  policy boundary;
- acquisition work additionally requires the source's existing policy to be
  `publisher-page` or the version to contain publisher-supplied full feed text;
- framing work requires a retained complete capture of at least 80 words and
  the existing retry/cooldown eligibility.

Publisher identity determines fairness buckets and whether a distinct slot is
missing; it never changes framing results, factual credibility, fusion scores,
or comparison content.

### Acquisition reserve

- Add `ENTITY_ARTICLE_ACQUISITION_EVENT_READY_PER_CYCLE`, default `2`, clamped
  to the existing acquisition batch size. Zero is permitted for controlled
  tests.
- Before ordinary enqueue selection, discover a bounded set of event-ready
  document versions through active membership and `NOT EXISTS` capture/task
  predicates. Do not scan article bodies.
- Order candidate events by the oldest missing eligible evidence, then stable
  event ID. Rotate publishers durably and select at most one document for an
  event/publisher before another event-ready repeat from that publisher.
- Enqueue only into available existing per-publisher and global backfill/fresh
  ceilings. The reserve cannot exceed caps, evict tasks, cancel retries, or
  convert historical work into fresh work.
- Mark priority through the existing task priority field and derive readiness
  again during processing. Do not add a mutable truth label to source evidence.
- Reserve processing capacity for due event-ready tasks while retaining space
  for fresh work and oldest retries. A failed event-ready request follows the
  same bounded retry, lease, redirect, host, DNS, byte, and extraction rules as
  every other task.
- Advance the event-ready enqueue/processing rotation cursor only after enqueue
  or processing is actually attempted. A saturated cap or disk shed must not
  masquerade as progress.
- Continue ordinary publisher-round-robin enqueue and processing with all
  capacity not consumed by the reserve.

### Semantic-framing reserve

- Add `ENTITY_SEMANTIC_FRAMING_EVENT_READY_PER_CYCLE`, default `2`, clamped to
  both the framing batch size and model-calls-per-cycle limit. Zero is permitted
  for controlled tests.
- Select event-ready captures publisher round-robin and oldest first within the
  publisher, before ordinary historical framing work. Deduplicate captures that
  also qualify for the fresh or retry lanes.
- Preserve the existing fresh-development path. When both reserves compete in
  a small batch, allocate at least one slot to fresh work when fresh eligible
  work exists, then event-ready work, then oldest retries/ordinary backfill.
- Use the same source-blind prompt, literal-span validation, model lanes,
  cooldown rules, and `semantic-framing-v2` storage contract. This reserve does
  not add model calls or borrow from another budget lane.
- A cooled or unavailable model leaves the capture eligible and does not advance
  its readiness cursor. `needs-model`, invalid output, and no-supported-signal
  outcomes retain their existing semantics.
- Once two independent publishers are completely assessed, existing world graph,
  fusion v3, and comparison v2 schedulers perform the remaining work without a
  new shortcut.

### Readiness audit and dashboard

- Extend `IntelligenceStore.comparison_readiness()` with bounded per-event gate
  rows containing event ID/title, independent-family count, member/captured/
  assessed publisher counts, missing eligible publisher keys, next stage, and
  the latest task status/error code. Return no article body or evidence span.
- Distinguish `policy-ineligible` from actionable `awaiting-enqueue`,
  `awaiting-capture`, `awaiting-framing`, `model-cooldown`, `source-unhealthy`,
  and `comparison-ready` states. A feed-only peer is not an acquisition failure.
- Add counts, oldest ages, recent throughput, and drain direction for the
  event-ready acquisition and framing queues.
- Extend the existing read-only comparison-readiness dashboard card with the
  actionable and policy-ineligible counts. Add no enqueue, scraping, merge,
  threshold, replay, or promotion controls.

### Replay and tests

- Add a frozen `event_readiness_pressure` replay case: a large ordinary backlog,
  one already captured peer awaiting framing, one approved uncaptured peer, and
  at least one feed-only peer. No network request may escape the fixture.
- Prove the approved missing peer reaches enqueue/capture and the retained peer
  reaches assessment before a high-volume publisher consumes a second reserved
  slot.
- Prove feed-only and unhealthy peers remain explicitly ineligible and are never
  fetched.
- Prove event-ready priority never bypasses global/per-publisher caps, disk soft
  or hard shedding, host allowlists, request-per-cycle limits, retry backoff, or
  leases.
- Prove fresh work retains bounded capacity and oldest retries/ordinary backfill
  continue making progress under continuous event-ready input.
- Prove reconstruction preserves publisher rotation and unchanged evidence is
  idempotent: one task per version/method, one capture per immutable input, one
  assessment per capture/method input, and one comparison per stable v2 hash.
- Prove publisher-label and arrival-order symmetry after key normalization.
- Prove no factual credibility, source policy, fusion threshold, membership, or
  prior comparison changes merely because work received scheduling priority.
- Run the full replay, intelligence, workload, dashboard, source-contract,
  fresh-latency, cutoff, literal-span, hard-negative, and fairness suites.

### Configuration and expected files

- `ENTITY_ARTICLE_ACQUISITION_EVENT_READY_PER_CYCLE=2`
- `ENTITY_SEMANTIC_FRAMING_EVENT_READY_PER_CYCLE=2`
- Expected code changes are limited to:
  `agent/intelligence/article_acquisition.py`,
  `agent/intelligence/framing.py`, `agent/intelligence/store.py`,
  `agent/intelligence/config.py`, `agent/intelligence/worker.py`,
  `agent/intelligence/replay.py`, `agent/intelligence/web.py`,
  `intelligence_dashboard/app.js`, `.env.example`, `README.md`, replay fixtures,
  tests, and this roadmap. Add migration 037 only if the measured query plan
  requires it.

### Explicitly out of scope

- Enabling `publisher-page` for BBC, France 24, The Guardian, Telegram, or any
  other currently feed-only source.
- Adding hosts, changing source contracts, bypassing publisher terms, or using
  generic web search/archive copies as substitute article captures.
- Increasing acquisition ceilings, request rates, model budgets, batch sizes,
  or reasoning-lane allowances.
- Lowering fusion/comparison thresholds, force-linking or manually merging a
  live event, auto-resolving reviews, or changing reporting-family lineage.
- New framing dimensions, prompt changes, publisher scoring, ideology/motive
  labels, factual-credibility changes, or promotion out of shadow.
- Regional baselines, change signals, watchlists, alerts, retention deletion,
  `VACUUM`, new connectors, or Implementation 5 work.

### Completion and handoff

Implementation 4A is code-complete when focused and full tests pass, the service
is healthy, event-ready scheduling is bounded/fair, and the audit distinguishes
actionable work from policy-ineligible peers without exposing retained text.

The prompt immediately after implementation is **bounded live acceptance**, not
Implementation 5: observe at least two event-ready cycles, verify ordinary and
fresh progress, and inspect any generated comparison for two distinct publisher
keys and independent families, complete literal-span assessments, stable cutoff,
v2 method, and shadow status. If no comparison appears, report the exact gate
and keep Step 7 open. Only after a genuine comparison closes Step 7 should the
next planning prompt detail Implementation 5.

## Implementation 5: bounded regional activity baselines

This remains blocked until Implementation 4A's live acceptance closes corrective
Step 7. It will build deterministic, versioned,
coverage-aware regional/event-type baseline snapshots with hierarchical fallback
for sparse regions and explicit unknown state during source outages. Its detailed
prompt must be written only after the Step 7 event and comparison contracts are
stable.

## Later milestone gates

### Close corrective Step 7

- Balanced multi-publisher article and framing coverage is demonstrated.
- Real canonical events produce comparisons from at least two independently
  assessed publishers.
- Publisher-blind symmetry, outage, correction, and cutoff replay tests pass.
- Selection framing stays unknown whenever acquisition or peer coverage is
  inadequate.
- Framing remains separate from factual credibility even after shadow evaluation.

### Baselines and change signals

- Baselines incorporate source coverage and reporting latency, use hierarchical
  fallback for sparse regions, and never interpret an outage as calm.
- Change signals are deterministic, evidence-linked, retractable, internal, and
  explicitly noncausal.

### Jarvis read-only product

- Ship the synchronized map/timeline and evidence drawer before expanding
  predictive behavior.
- Add citation-complete viewport briefings and watchlists with no delivery.

### Prediction, delivery, and promotion

- Forecasts remain shadow until out-of-time calibration and resolution-coverage
  gates pass.
- Alerts require explicit watchlist opt-in and always pass through Entity Core.
- Full replay, false-alert, geographic/language coverage, licensing, retention,
  security, and workload audits gate operational promotion.
