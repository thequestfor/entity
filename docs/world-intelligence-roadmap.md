# Entity World Intelligence Roadmap

This is the canonical implementation plan for Entity's global intelligence
system. It is deliberately separate from Entity's identity as a personal
agent.

## Product boundary

- **Entity Core** owns wake word, conversation, memory, calendar, alarms,
  notifications, room control, planning, and personal autonomy.
- **World Intelligence** owns public-source collection, evidence evaluation,
  event understanding, hypotheses, forecasts, and calibration.
- **Jarvis Mode** will be an optional operations interface over World
  Intelligence. Requests to take action must still pass through Entity Core's
  planner, permissions, confirmations, and durable task systems.

Jarvis Mode must never replace the primary assistant, bypass action controls,
or turn raw intelligence signals directly into physical actions.

## Sixteen-step implementation plan

1. [x] Add the universal world-event graph.
2. [x] Add the licensed source registry and connector contracts.
3. [x] Integrate conflict, humanitarian, and emergency feeds.
4. [x] Add global weather and infrastructure layers.
5. [ ] Add maritime activity intelligence. *(Deferred; not required for the current MVP.)*
6. [x] Fuse observations into evolving world events.
7. [ ] Enrich and correlate open-source reports. *(Text-first enrichment, batched translation, location, lineage, unified credibility, protected model capacity, canonical assessments, and engineering feeds delivered; bounded media derivation remains.)*
8. [ ] Learn bounded regional activity baselines.
9. [ ] Generate evidence-linked world change signals.
10. [ ] Add the autonomous predictive world engine.
11. [ ] Calibrate forecasts by domain, region, and horizon.
12. [ ] Add the separate Jarvis timeline and intelligence-map interface.
13. [ ] Add Jarvis viewport briefings and watchlists.
14. [ ] Deliver selected intelligence alerts through Entity Core.
15. [ ] Add historical replay, bias, and false-alert evaluations.
16. [ ] Enforce source licensing, security, and workload limits end to end.

## Target situation monitor

The intended product is a read-only, map-first operational picture in the
spirit of Liveuamap and MonitorTheSituation, with an Entity-native interface:
an event map synchronized with a chronological feed, evidence inspection,
source and confidence filters, regional briefings, watchlists, and optional
spoken or pushed summaries.  The interface may feel immediate, but it must be
truthful about source latency and must never label a feed as real time when it
is delayed, sampled, or intermittently unavailable.

"Jarvis-ified" means Entity can explain the visible region, summarize what
changed, expose competing interpretations, and answer questions about cited
evidence.  It does not mean autonomous command and control.  World
Intelligence remains read-only, and any eventual delivery or action crosses
the Entity Core policy and confirmation boundary.

The named products are interaction references only.  Entity must not scrape,
republish, or imitate their protected content, branding, or private APIs.

## Preliminary implementation map

This map records the intended architecture before individual step design and
source review.  Source choices are candidates until their terms, attribution,
retention, geographic coverage, and operational limits are captured in the
source registry.  Each step should extend the existing connector -> immutable
document version -> deterministic projection pipeline wherever the input is
evidence.  High-volume state caches must remain explicitly separate from
factual corroboration.

### 1. Universal world-event graph -- delivered

- Keep source documents and versions as the immutable evidence boundary.
- Project situations and native geographic observations into stable world
  events, entities, observations, and noncausal relations.
- Retain the pre-created schemas for infrastructure assets, movement tracks,
  regional baselines, change signals, watchlists, and alerts for later steps.
- Do not perform semantic event fusion until step 6.

### 2. Licensed source registry and connector contracts -- delivered

- Require stable source identity, epistemic role, independence family,
  allowlisted HTTPS hosts, access class, license, attribution, retention, and
  caveats for every connector.
- Validate both the configured base URL and every derived request URL.
- Keep credentials out of URLs, stored evidence, errors, and audit output.
- Expand this registry rather than creating step-specific source policy code.

### 3. Conflict, humanitarian, and emergency feeds -- delivered

- ACLED, HDX HAPI, and Copernicus EMS enter through bounded, read-only
  connectors and retain provider-specific provenance.
- Curated reports, measurements, and mapping activations keep different
  evidence roles; none is silently promoted to direct observation.
- Existing hazard sources continue to supply native geospatial observations.

### 4. Global weather and infrastructure layers

**Outcome:** add globally queryable environmental context and critical-place
reference data without presenting a forecast as an observation or an asset's
presence as evidence of its operating status.

- Add a licensed global forecast connector.  Open-Meteo is the leading initial
  candidate because Entity Core already has a compatible client, but World
  Intelligence must use separate configuration, cadence, storage, provenance,
  and explicit service-term acceptance.
- Represent every forecast with provider/model, run time, capture time, valid
  time, grid geometry, variables, units, and expiry.  Normalize forecasts as
  `SourceItem` evidence and deterministically materialize a bounded forecast
  layer; do not route ordinary forecast cells through hazard claim extraction.
- Use a configurable coarse global grid plus higher-resolution configured
  regions.  Cap cells, horizons, variables, response bytes, requests per cycle,
  retained runs, and backfill work.  Missing or stale cells display as unknown.
- Materialize licensed airport and port reference datasets into the existing
  `infrastructure_assets` table.  OurAirports is the initial airport candidate;
  the NGA World Port Index is the initial port candidate after endpoint and
  redistribution review.  Power, communications, road, and rail datasets are
  added only when a maintained global source passes the same review.
- Add immutable asset versions and stable `(source_id, external_id)` identity so
  renamed, removed, and superseded assets remain auditable.
- Expose bounded viewport APIs and simple toggles in the current engineering
  dashboard.  The dedicated situation-monitor experience remains step 12.

**Acceptance:** fixture-backed connectors are idempotent; issue time and valid
time cannot be confused; static assets and forecasts cannot corroborate factual
claims or create outages; viewport queries handle limits and the antimeridian;
attribution is visible; backfills are resumable; stale coverage is explicit.

### 5. Maritime activity intelligence -- deferred

**Outcome:** provide a bounded maritime movement layer and port context without
inferring identity, intent, legality, hostility, or destination from a track.

- Add a provider-neutral AIS contract and begin with one explicitly licensed,
  opt-in provider.  Do not scrape consumer vessel-tracking sites or make an
  undocumented public endpoint a production dependency.
- Resolve provider vessel identifiers into `world_entities`; write timestamped
  positions to `movement_tracks` with source, accuracy, navigation status, and
  capture latency.  Retain only the licensed history window.
- Maintain a current-state vessel cache for low-latency map rendering.  Keep
  cache rows and raw movement alone out of situations, claims, publisher
  reputation, and forecast resolution evidence.
- Deterministically calculate clearly labeled track facts such as speed change,
  course change, geofence entry, and proximity to a known port.  A port call,
  destination, rendezvous, or anomalous behavior remains unknown unless the
  applicable evidence and later inference step support it.
- Bound monitored regions, vessels, points per vessel, polling cadence, request
  volume, map result count, and track retention.  Degrade to stale/unknown when
  the provider is unavailable.

**Acceptance:** duplicate and out-of-order positions are safe; impossible
coordinates and speeds are rejected; source deletion/retention requirements are
enforced; movement does not create intent claims; map clustering remains usable
at world zoom; provider failure cannot block the main intelligence worker.

#### Step 5 implementation design

**Provider approval gate**

- Production collection remains disabled until one provider has a documented
  API and an approved source contract covering authentication, permitted use,
  attribution, storage and redistribution, retention/deletion, rate limits,
  geographic coverage, and service latency.  Consumer-map scraping and
  undocumented endpoints are out of scope.
- Add the selected provider to `source_registry.py` with an `observation` role,
  a provider-specific independence family, HTTPS host allowlist, review date,
  retention limit, and caveats.  Enabling the adapter is the operator's explicit
  acceptance of those recorded terms; credentials remain outside stored rows,
  cursors, URLs, logs, fixtures, and API responses.
- Build and test against a fixture provider first.  Provider selection and live
  smoke testing are a separate, reviewable gate, so they cannot delay the safe
  storage and rendering foundation or silently weaken it.

**Data boundary and contracts**

- Introduce provider-neutral `MaritimePosition` and `MaritimeBatch` records and
  a small connector protocol in `agent/intelligence/maritime.py`.  A position
  carries provider vessel key, observed and captured times, latitude,
  longitude, speed over ground, course over ground, optional heading,
  navigation status, positional accuracy, and carefully bounded identifiers.
- Do not normalize routine positions into `SourceItem`.  They therefore never
  become documents, claims, situations, publisher reputations, world-event
  observations, forecast outcomes, or acquisition targets.  A later event can
  cite a separately collected report about a vessel, but not promote a track
  point into a factual narrative by itself.
- Define one adapter method, `poll(cursor) -> MaritimeBatch`, with opaque,
  resumable cursors and an explicit coverage timestamp.  The core validates and
  stores normalized records; provider adapters only authenticate, page, map
  fields, and report provider deletion instructions.

**Migration 026 and identity**

- Extend `movement_tracks` with capture time, provider position ID, positional
  accuracy, and an ingestion hash.  Preserve the existing unique key and add a
  provider-position unique index when an upstream ID exists, plus viewport/time
  and retention indexes.
- Add `maritime_entity_identifiers` for source-scoped provider IDs, MMSI, IMO,
  and call signs with validity intervals.  Create stable `world_entities` of
  type `vessel`; never merge entities from name or call sign alone.  Prefer an
  explicit provider identity or IMO, treat MMSI as time-bounded, and retain
  superseded mappings for audit.
- Add `vessel_states` as the latest-position cache, keyed by entity and source.
  It includes freshness state (`current`, `stale`, or `unknown`) and only moves
  forward when a newer observation arrives.  History remains append-only until
  the licensed retention job removes an expired partition/batch.
- Add `maritime_track_facts` for deterministic, non-interpretive calculations
  and `maritime_projection_state` for resumable derivation and retention work.
  Every derived row records its algorithm version and input point IDs.

**Validation and deterministic projection**

- Reject missing vessel keys, malformed timestamps, future-skewed or over-age
  positions, coordinates outside valid ranges, non-finite numbers, invalid
  courses/headings, and speeds above a configurable physical ceiling.  Limit
  response bytes, pages, positions per poll, positions per vessel, and total
  vessels before opening a transaction.
- Insert duplicates idempotently.  Accept a valid late point into retained
  history but never let it roll back `vessel_states`; positions older than the
  retention boundary are discarded.  Use observed time for motion and capture
  time only for latency/freshness.
- Calculate only reproducible facts from adjacent same-source points: reported
  speed/course change, calculated displacement/speed, configured geofence
  entry/exit, and proximity to a referenced port.  Skip calculations across
  excessive time gaps or implausible jumps.  Label proximity as `near_port`,
  never `port_call`, and do not emit anomaly, rendezvous, destination, or intent
  claims in this step.
- Run pruning in small indexed batches.  Persist deletion counts and the
  governing source-policy version so retention is testable and auditable.

**Worker and failure isolation**

- Add a `MaritimeMonitor` beside the existing aircraft monitor.  It registers
  the approved source policy, owns its independent due time and cursor, and
  invokes one bounded projection/retention cycle after a successful poll.
- Catch provider, parsing, projection, and pruning failures at the maritime
  boundary; use the worker's exponential source backoff and retain the last
  good cache with an increasingly stale label.  Maritime updates do not set
  `analysis_due` and cannot block other connectors or cognition.
- Default the feature and every live adapter to disabled.  Proposed settings:
  `ENTITY_MARITIME_ENABLED`, `ENTITY_MARITIME_PROVIDER`, provider credential
  variables, region/geofence definitions, poll interval, maximum vessels,
  maximum positions per cycle and vessel, maximum speed, stale interval, and
  retention days.  Clamp every numeric value in `IntelligenceConfig`.

**Read APIs and engineering dashboard**

- Add `GET /api/intelligence/map/vessels` for current states with bounding box,
  freshness, source, zoom, and bounded limit filters.  At low zoom return
  server-side spatial clusters rather than individual vessels.
- Add `GET /api/intelligence/map/vessels/{entity_id}/track` for a bounded time
  window and point count.  Return provenance, observation/capture times,
  latency, accuracy, freshness, and attribution; never return credentials or a
  provider payload wholesale.  Handle antimeridian viewports and tracks.
- Add an off-by-default `Vessels` toggle to the existing engineering map.
  Render current/stale states distinctly, draw a selected vessel's limited
  trail only at suitable zoom, and state that positions may be delayed or
  incomplete.  The synchronized operational timeline remains step 12.

**Delivery slices**

1. Migration 026, normalized contracts, fixture adapter, identity resolver,
   validation, idempotent storage, current-state cache, and retention worker.
2. Deterministic track-fact projection and port proximity using the step 4
   infrastructure layer, with all inference exclusions locked by tests.
3. Viewport/track APIs, low-zoom clustering, dashboard toggle, freshness and
   attribution UI, and API contract tests.
4. Provider contract review, production adapter, opt-in configuration, bounded
   live smoke test, operator documentation, and final acceptance audit.

**Acceptance test matrix**

- Replayed pages and duplicated provider IDs create no duplicate tracks;
  out-of-order points preserve history without rewinding current state.
- Invalid coordinates, timestamps, headings, and impossible speeds are rejected
  without partially writing a batch.  Pagination and byte/item bounds are
  exercised with hostile fixtures.
- Identifier changes preserve old mappings, and two vessels sharing a name or
  call sign are not merged.  MMSI reuse does not rewrite historical ownership.
- Fresh, stale, and unknown transitions use provider coverage time, not local
  request time.  Provider failure leaves the last good state visible as stale
  and the main worker completes normally.
- Retention and provider deletion fixtures remove only authorized track/state
  rows in bounded batches while preserving audit counts and unrelated sources.
- Tracks and derived facts produce zero situations, claims, publisher scores,
  world events, verification evidence, or forecast resolutions.
- Viewport and track queries enforce limits, cross the antimeridian correctly,
  cluster at world zoom, expose attribution/freshness, and avoid N+1 queries.

Step 5 is complete only after slices 1-4 pass this matrix.  Until a provider
contract is approved, slices 1-3 may merge as disabled infrastructure, but the
roadmap checkbox remains open.

### 6. Fuse observations into evolving world events -- delivered

**Outcome:** turn related reports, measurements, hazard features, and eligible
observations into stable events whose history survives updates, contradictions,
merges, and splits.

- Introduce a deterministic event-fusion engine after ingestion and native
  projections.  Candidate generation uses category compatibility, geographic
  distance, temporal overlap, grounded entities, identifiers, and reporting
  lineage before any model-assisted review.
- Upgrade the current situation clustering/world-graph projection path so one
  canonical event can contain many evidence observations without treating
  syndication as independent corroboration.
- Store every link decision with method, score components, evidence cutoff, and
  outcome.  Ambiguous matches enter a review queue.  Never destructively merge
  source documents or erase the losing side of a contradiction.
- Support event lifecycle transitions, correction, merge aliases, and reversible
  split/reattribution operations.  Causal relations remain `noncausal` unless a
  separate evidence-backed method explicitly establishes a stronger status.
- Recompute only affected events in short, resumable batches and preserve stable
  IDs across restarts.

**Acceptance:** replaying identical evidence produces identical events; nearby
but distinct incidents remain separate; late revisions attach without rewriting
history; syndicated sources count once; ambiguous merges remain pending; fusion
is cutoff-safe and migration/backfill work is resumable.

#### Step 6 implementation design

**Architectural transition**

- Keep immutable documents, document versions, claims, `situations`, and the
  existing `EventClusterer`.  They remain the ingestion and interpretation
  layer, so step 6 does not destructively rewrite `situation_documents` or
  invalidate the current dashboard and reasoning stack.
- Make `world_event_observations` the inputs to a new `EventFusionEngine`.
  Situation- and native-feature-derived world events become seed events, not a
  permanent one-to-one canonical boundary.  Fusion can attach observations
  from several seeds to one canonical event while retaining every original ID
  as a resolvable alias.
- Treat event membership as a versioned decision.  A document revision creates
  another observation linked to its predecessor; it never mutates the captured
  content.  Rejected, superseded, corrected, and reattributed observations stay
  auditable.
- Do not use weather forecasts, infrastructure references, private mail,
  prediction markets, raw movement caches, or other contextual state as fusion
  evidence.  Eligible source policies retain their distinct epistemic roles;
  discovery reports can suggest a candidate but cannot manufacture independent
  corroboration.

**Next migration and audit model**

- Migration `026_event_fusion.sql` extends
  `world_event_observations` with lifecycle status, predecessor/supersession
  links, reporting-family key, source-policy snapshot/version, and effective
  occurrence precision.
- Add `world_event_memberships` with observation, canonical event, active
  interval, decision ID, action, and method.  Enforce at most one active
  canonical membership per observation while retaining closed memberships.
- Add `world_event_fusion_decisions` for every evaluated observation/candidate
  pair.  Store the input cutoff, feature version, score components, hard vetoes,
  decision (`link`, `create`, `review`, or `reject`), model involvement, and
  creation time under a deterministic decision ID.
- Add `world_event_fusion_reviews` for ambiguous candidates and
  `world_event_operations` for accepted review, merge, split, reattribution,
  correction, and rollback operations.  Each operation stores before/after
  membership snapshots and an inverse operation so reversal never requires
  reconstructing overwritten state.
- Add `world_event_aliases` from retired seed/merged event IDs to the current
  canonical ID.  Add immutable `world_event_versions` containing the aggregate
  snapshot, membership hash, evidence cutoff, algorithm version, and reason for
  change.  Existing links remain navigable after merges or corrections.
- Add `world_event_fusion_state` with separate recent and historical lanes so
  new observations are handled promptly while backfill advances in bounded,
  resumable batches.  Record errors without advancing past failed work.

**Candidate generation**

- Generate a small indexed candidate set before scoring.  Use a versioned
  compatibility matrix for event categories rather than requiring identical
  source labels; for example, a curated conflict report and a news report can
  be compatible while an earthquake and a cyber advisory cannot.
- Apply category-specific time windows and geographic radii using the recorded
  location precision.  Include exact provider/event identifiers, normalized
  grounded entities, country/region, source reporting family, document
  relationships, lexical signature, and optional frozen embedding version.
- Search active canonical events first, then recently resolved events when a
  late revision could reasonably belong to them.  Cap candidates per
  observation, events touched per cycle, lookback, geographic radius, and total
  recomputations.
- Add hard vetoes before scoring: conflicting authoritative identifiers,
  mutually incompatible categories, non-overlapping precise locations or time
  windows, distinct earthquake identifiers/epicenters, and explicit prior
  human separation.  A model cannot override a veto.

**Deterministic decisions**

- Score identifier agreement, category compatibility, temporal overlap,
  precision-aware geographic overlap, entity agreement, lexical similarity,
  and reporting lineage as separately stored components.  Version all weights,
  thresholds, mappings, and feature extraction.
- Use three outcomes: high-confidence deterministic links attach
  automatically; middle-band candidates enter review without changing
  membership; low scores create a new seed event.  Ties use a documented stable
  ordering, never database row order.
- Copied and syndicated documents may attach to the same event but share one
  reporting-family contribution.  `source_count` remains available for
  provenance; add `independent_family_count` for corroboration and confidence.
- Local embeddings may narrow or rank candidates only when their exact model
  and vector version are frozen.  Model-assisted judgment may annotate the
  review queue but cannot auto-link, merge, split, establish causation, or alter
  a hard deterministic result in this step.
- Create canonical event IDs from the deterministic seed observation.  A late
  observation never renames an event.  When two existing events merge, retain
  the oldest stable canonical ID (with a lexical-ID tie-break) and alias the
  other; replaying the same capture order produces the same IDs and decisions.

**Aggregate recomputation and lifecycle**

- Recompute an affected event from its active memberships inside one
  transaction instead of incrementally adjusting counters.  Derive title,
  category, location/geometry, occurrence interval, severity, confidence,
  source count, independent-family count, contradictions, first/last capture,
  and freshness with deterministic precedence rules.
- Prefer exact authoritative geometry and identifiers over inferred values;
  otherwise use precision-weighted consensus.  Never average distant points
  whose compatibility was not established.  Record competing locations rather
  than fabricating a centroid.
- Confidence combines evidence-role quality and independent reporting families,
  while preserving explicit contradictions.  Syndication adds provenance but
  not independent confirmation.  Event fusion does not resolve claim truth;
  it only groups observations believed to concern the same occurrence.
- Use explicit lifecycle states such as `active`, `monitoring`, `resolved`,
  `corrected`, `merged`, and `archived`.  Absence of new reporting cannot alone
  prove resolution.  Provider closure or correction changes the relevant
  observation status and triggers recomputation rather than deleting history.
- Keep all event-to-entity and event-to-event relations `noncausal` unless a
  separate evidence-backed method explicitly supports another status.  Spatial
  or temporal proximity never becomes a causal edge.

**Merge, split, and correction semantics**

- A merge closes the losing event's active memberships, opens equivalent
  memberships on the winner, writes an alias and operation snapshot, and emits
  a new winner version.  It never moves source documents or deletes the losing
  event/version history.
- A split selects explicit observation IDs, creates or restores a stable target
  event, versions both affected events, and records the inverse membership
  mapping.  Reattribution uses the same machinery for one observation.
- Automatically reopen a review instead of silently changing membership when
  late evidence introduces a hard conflict with the original link decision.
  Human decisions and explicit separation constraints are durable inputs to
  future candidate generation.
- Expose mutation operations only through an internal service/CLI initially.
  Public dashboard endpoints remain read-only until step 13 introduces
  authenticated, same-origin mutation patterns.

**Worker order and failure isolation**

- Run fusion after `WorldEventGraphEngine` has projected new observations and
  before baselines, change signals, or forecasting consume events.  It has its
  own enable flag, batch size, recent quota, historical quota, candidate cap,
  thresholds, category windows, and maximum events recomputed per cycle.
- One malformed observation or failed review annotation cannot block other
  observations or the main intelligence worker.  Commit at a bounded unit,
  retain the error and retry position, and use the existing worker's outer
  exception isolation.
- Only successful committed fusion changes count as downstream changes.  Model
  unavailability leaves deterministic results intact and review items pending.
  No fusion path performs an external action or triggers Entity Core directly.

**Read APIs and engineering visibility**

- Update world-event list/detail queries to resolve aliases and return canonical
  status, independent-family count, freshness, version, membership count,
  contradictions, and last decision cutoff without N+1 queries.
- Add bounded read endpoints for an event's membership/version history and the
  fusion review queue.  Each observation exposes its direct document/version,
  source policy, reporting family, and link rationale; copied text need not be
  redistributed to explain the decision.
- Extend the engineering dashboard with fusion health, pending reviews, merge
  aliases, and an observation-membership inspector.  The synchronized public
  timeline and polished operational interaction remain step 12.

**Delivery slices**

1. Migration, eligibility rules, observation revision lineage, fusion state,
   immutable decisions, memberships, aliases, event versions, and store APIs.
2. Versioned candidate generation, hard vetoes, deterministic scoring,
   create/link/review outcomes, recomputation, and worker integration.
3. Lifecycle transitions plus transactional merge, split, correction,
   reattribution, and rollback services with durable separation constraints.
4. Alias-aware read APIs, review/history views, dashboard diagnostics,
   resumable backfill, replay fixtures, documentation, and acceptance audit.

**Acceptance test matrix**

- Replaying identical observations in the same capture order yields identical
  canonical IDs, decisions, memberships, aggregates, and event-version hashes.
  Re-running a batch creates no duplicate decisions or versions.
- Two nearby but distinct incidents remain separate under category-specific
  identifier, time, and location vetoes; compatible multi-source reports link.
  Ambiguous matches stay pending and do not alter either event.
- Late document revisions attach to the correct event, supersede only their
  predecessor observation, and do not rewrite older documents, decisions, or
  event versions.  Deleted/corrected reports trigger deterministic recompute.
- Copied and syndicated sources increase provenance counts but contribute one
  independent reporting family.  Independent corroboration remains distinct
  from source count and publisher credibility.
- Merge, split, reattribution, and rollback restore the exact prior active
  memberships and preserve aliases/history.  Human separation constraints
  prevent the same automatic merge from recurring.
- Every candidate score reconstructs from stored versioned components at its
  cutoff.  Later evidence, embeddings, source-policy changes, or model output
  cannot leak into an earlier replay.
- Context layers, private mail, forecasts, markets, and raw movement create no
  fusion candidates.  Fusion creates no causal relations, alerts, actions, or
  forecast resolutions.
- Recent work cannot starve historical backfill; failed units retry without
  cursor loss; caps hold under adversarial candidate volume; worker completion
  and other sources remain unaffected by fusion failure.
- Alias-aware viewport/detail queries are bounded, antimeridian-safe where
  applicable, attribution-complete, and return the same canonical event through
  old and current IDs.

Step 6 is complete only after all four slices pass this matrix and a replay set
containing duplicates, syndication, corrections, close-but-distinct incidents,
ambiguous candidates, merges, and splits remains deterministic.

### 7. Enrich and correlate open-source reports

**Outcome:** turn sparse text-first Telegram and similar public reports into
grounded, channel-aware evidence that can join the same events as news and
authoritative feeds without mistaking repetition, political framing, or model
output for confirmation.

**Delivered foundation:**

- Telegram documents already carry channel-specific publisher identities rather
  than sharing one platform-wide reputation.
- Grounded document-location inference now runs before clustering.  It prefers
  source metadata and local infrastructure references, may use one bounded model
  extraction with a verbatim evidence span, and resolves eligible place names
  through a free geocoder.  It stores method, confidence, precision, and the
  evidence excerpt separately from the immutable captured source version.
- Operator-configured channel profiles can set factual-reliability and framing
  priors independently without publishing the selected accounts. Delayed
  independent outcomes may move factual reliability in either direction, and no
  prior proves or refutes an individual claim.
- Ambiguous location text remains unresolved and is retried.  Corpus audit
  fixtures include adversarial place-name collisions such as Lebanon the country
  versus municipalities named Lebanon.
- A versioned enrichment lane detects scripts/languages, stores model/provider,
  input hash, confidence and evidence spans, and writes English translations as
  derived fields without replacing captured text.  Model use is bounded and
  reports that still require it remain explicitly queued.
- Event category, actors, event time, place candidates, URLs, quoted authorities,
  forward origin, and media metadata are extracted and deterministically
  validated against captured evidence.  Media is not downloaded.
- Exact reposts and known forwards receive shared reporting-family lineage and
  auditable document relationships.  They cannot inflate independent-source
  counts merely by being repeated across channels.
- Enrichment invalidates affected derived features, refreshes world-event
  observations, and reruns versioned, reversible event fusion so historical
  Telegram posts can join canonical events shared with news and authoritative
  feeds.
- The engineering dashboard exposes a first-class early-report feed with the
  original post, derived translation/category/location, channel trust and framing,
  and canonical-event/independent-family correlation status.
- A conservative unified publisher assessment now combines configured baselines
  with independently eligible claim outcomes.  Positive movement remains locked
  until maturity, refutations can lower confidence immediately, every changed
  input creates immutable history, and framing remains a separate signal.
- Reasoning capacity is partitioned into worldview, grounding, and forecast lanes
  with per-lane reserves and maxima.  Enrichment batches several reports per call,
  while completed, failed, invalid, abandoned, and budget-denied attempts are
  auditable without retaining prompt text.
- Canonical fused events receive deterministic epistemic assessments that keep
  direct observations, corroborated reports, early signals, disputes, competing
  hypotheses, and unknowns distinct under `truth-seeking-v1`.  This assessment,
  rather than a generated narrative, is the new engineering world-picture layer.

**Remaining implementation:**

- Add bounded media enrichment for public captions, images, video keyframes, and
  audio.  OCR or transcription is derived evidence with confidence and exact
  media provenance, not a direct observation.  Unsupported, oversized, deleted,
  or unavailable media remains explicit.
- Separate factual accuracy, attribution quality, revision discipline,
  independence, timeliness, and framing in channel profiles.  Topic-specific
  reliability requires sufficient independently resolved samples and otherwise
  shrinks to the configured channel and platform priors.
- Expand the engineering view with dedicated unresolved queues, copied-family
  drill-down, profile rationale, and the evidence behind each learned-score
  change.  The polished synchronized feed remains step 12.

**Acceptance:** English and non-English fixtures join the same event when their
grounded facts agree; ambiguous locations do not receive coordinates; forwarded
or copied posts count as one reporting family; media-only posts never become
specific claims without derived evidence; high-bias sources may contribute true
facts without being treated as neutral; high-reliability sources can be
contradicted; all learned adjustments reconstruct from independent outcomes;
historical re-correlation is resumable, reversible, cutoff-safe, and idempotent.

Step 7 is complete only after translation, attribution, media enrichment,
cross-source re-correlation, channel-profile auditability, and adversarial replay
fixtures pass these acceptance conditions.  Location inference and channel priors
alone do not close the step.

### 8. Learn bounded regional activity baselines

**Outcome:** estimate what the collected system normally observes by region,
event type, season, and time bucket while separating real-world activity from
collection coverage.

- Populate `regional_baselines` from fused events and eligible measurement
  streams using deterministic, versioned feature definitions.
- Start with coarse spatial cells and country/region aggregates.  Add seasonal,
  weekday, and hour buckets only when sample counts support them.
- Track source uptime, expected reporting delay, coverage mix, observation
  exposure, sample size, dispersion, cutoff, and confidence beside every rate.
- Use hierarchical shrinkage toward broader regional and global priors when
  local data are sparse.  Publish `unknown` rather than a zero baseline when
  coverage is inadequate.
- Train in bounded historical batches and freeze versioned snapshots for later
  replay and forecast features.

**Acceptance:** future evidence cannot leak into a baseline snapshot; source
outages do not appear as calm; sparse cells fall back conservatively; minimum
sample and coverage gates are enforced; rebuilding a version is deterministic.

### 9. Generate evidence-linked world change signals

**Outcome:** identify material deviations and state transitions for human review
without turning statistical novelty into a factual or causal conclusion.

- Compare recent fused-event and eligible measurement windows with the matching
  regional baseline.  Begin with rate increase, severity increase, geographic
  spread, first-seen category, escalation/de-escalation, and coverage-loss
  signals.
- Write versioned results to `world_change_signals` with observed value, expected
  value, score, uncertainty, baseline version, cutoff, and exact evidence IDs.
- Require deterministic prioritization, minimum coverage, persistence windows,
  deduplication, cooldowns, expiry, and retraction when underlying evidence is
  corrected.
- Display the signal as "change detected by Entity" rather than as an event or
  cause.  Models may summarize prioritized signals but may not invent them.
- Keep signals internal in this step; watchlist matching and delivery occur in
  steps 13 and 14.

**Acceptance:** synthetic spikes are detected; collection outages are labeled as
coverage changes; ordinary seasonal activity is suppressed; every score can be
reconstructed; corrections retract rather than delete a signal; no alert is
delivered externally.

### 10. Add the autonomous predictive world engine

**Outcome:** extend the existing experimental forecasting stack into a bounded,
portfolio-driven engine over fused events and change signals.

- Reuse the durable reasoning queue, evidence cutoffs, forecast components,
  resolution attempts, base rates, geospatial snapshots, and shadow/active gates
  that already exist.  This step is an integration and hardening effort, not a
  second forecasting subsystem.
- Generate forecasts only from deterministically prioritized, sufficiently
  evidenced events or change signals.  Require a falsifiable outcome, deadline,
  resolution criterion, domain, region, horizon, and frozen evidence packet.
- Maintain a portfolio across domains, regions, horizons, positive/negative
  outcomes, and uncertainty levels so salience does not consume the entire
  budget.
- Combine base rate, deterministic features, market signal when applicable, and
  bounded model judgment as separately inspectable components.  No component is
  allowed to masquerade as factual evidence.
- Run in shadow mode until step-11 calibration and resolution-coverage gates
  promote a version.  Forecasts never directly create notifications or actions.

**Acceptance:** jobs are idempotent and leased; budgets and reserved lanes hold
under failure; forecasts are cutoff-safe and resolvable; unsupported or vague
questions are rejected; portfolio caps hold; no forecast enters factual claims.

### 11. Calibrate forecasts by domain, region, and horizon

**Outcome:** measure and correct predictive performance at useful subgroups
without overfitting sparse outcomes or hiding poor resolution coverage.

- Extend the existing Brier score, log-loss, expected-calibration-error,
  base-rate, out-of-time ensemble, and promotion-gate machinery with domain,
  region, and horizon buckets.
- Use hierarchical calibration: global priors first, then domain and horizon,
  and only then regional adjustments when minimum resolved counts and outcome
  diversity are met.
- Track unresolved, ambiguous, late, and manually overturned resolutions.  Show
  both score and resolution coverage so selective resolution cannot improve the
  apparent result.
- Compare every candidate against the frozen prior production version using
  out-of-time validation and worst-subgroup degradation gates.  Publisher or
  source identity remains excluded as a predictive feature.
- Version calibration maps and retain the raw pre-calibration probability.

**Acceptance:** calibration improves or matches the baseline out of time;
probabilities remain bounded and monotonic; sparse subgroups shrink to broader
priors; worst-group regressions block promotion; all metrics reproduce from
stored forecasts and resolutions.

### 12. Add the separate Jarvis timeline and intelligence-map interface

**Outcome:** deliver the dedicated situation monitor while keeping the existing
dashboard available as an engineering and epistemic-inspection surface.

- Build a separate localhost application/route with a synchronized map and
  reverse-chronological event timeline.  Selecting a marker selects its timeline
  card and evidence drawer; timeline scrubbing changes the map cutoff.
- Support layers for fused events, native hazards, weather, infrastructure,
  maritime tracks, and change signals with source, time, severity, confidence,
  and status filters.  Cluster or aggregate dense layers by zoom.
- Give each event a compact operational card: what was reported, where and when,
  what changed, confidence, independent-source count, contradictions, freshness,
  and direct evidence links.
- Add an Entity commentary panel that receives a bounded, structured viewport
  packet.  It must distinguish visible observations, reports, inferences,
  forecasts, and coverage gaps in both text and visual language.
- Use the existing read-only service boundary and outbox/revision semantics for
  incremental updates.  Prefer reconnectable server-sent events or bounded
  polling; never make the browser query third-party intelligence sources.
- Meet keyboard navigation, reduced-motion, contrast, screen-reader, and
  responsive-layout requirements.  Avoid copying the named reference products'
  branding or proprietary presentation.

**Acceptance:** map and timeline remain synchronized under filters and replay;
every card reaches its evidence; stale and uncertain data are obvious; dense
world views remain bounded; reconnect resumes without duplication; no interface
control can trigger an external action.

### 13. Add Jarvis viewport briefings and watchlists

**Outcome:** let the operator ask "what matters here?" and persist bounded areas
or topics of interest without automatically notifying them.

- Build viewport packets deterministically from the current bounding box, time
  window, enabled layers, top changes, contradictions, coverage, and evidence
  IDs.  Cache by request fingerprint and evidence cutoff.
- Generate grounded briefings from those packets with a deterministic fallback.
  Every sentence must map to packet evidence or be explicitly labeled as an
  inference, forecast, uncertainty, or coverage limitation.
- Activate `world_watchlists` for geographic areas, entities, event types,
  thresholds, time windows, and source constraints.  Validate a small versioned
  query schema rather than storing executable expressions.
- Add loopback-only, same-origin mutation endpoints for watchlist management
  with request-size limits and CSRF protection.  Watchlists default to no
  notification.
- Match fused events and change signals into a durable watchlist inbox with
  deduplication and explainable match reasons.

**Acceptance:** briefing output is cutoff-safe and citation-complete; malformed
watchlist queries are rejected; dateline-crossing regions work; repeated matches
deduplicate; empty coverage is reported honestly; creating a watchlist causes no
external delivery.

### 14. Deliver selected intelligence alerts through Entity Core

**Outcome:** deliver explicitly opted-in, high-value watchlist matches through
the personal assistant's existing presence, importance, notification, and audit
controls.

- World Intelligence writes eligible records to `world_alerts`; it never calls
  speech, ntfy, calendar, or another actuator directly.
- Entity Core consumes pending alerts through a dedicated observer, applies
  watchlist opt-in, severity, confidence, independent-source, freshness,
  quiet-hour, presence, cooldown, and duplicate gates, then chooses speak,
  notify, defer, or suppress.
- Format alerts with what changed, where, source count, confidence, uncertainty,
  and a localhost evidence link.  Forecast-based alerts must say "forecast" in
  the title and body.
- Record every decision, delivery attempt, acknowledgement, suppression reason,
  and retry.  Delivery failure must not mark an alert delivered.
- Require confirmation for any later workflow that proposes action in response
  to intelligence; this step itself adds no such action.

**Acceptance:** no opt-in means no delivery; private-mail-only evidence cannot
produce a public alert; cooldowns survive restart; presence and quiet hours are
honored; retries are idempotent; all delivery paths pass through Entity Core.

### 15. Add historical replay, bias, and false-alert evaluations

**Outcome:** test the entire monitor as it would have behaved at a past cutoff
and quantify misses, false alarms, latency, calibration, and coverage inequity.

- Add an isolated replay runner that reads immutable versions in capture-time
  order, uses the then-valid source policies and model versions, and never
  modifies the live database.
- Freeze fixtures for representative conflict, disaster, weather, maritime,
  correction, syndication, source-outage, and no-event periods.  Include hard
  negatives and near-duplicate incidents.
- Measure event merge/split quality, detection latency, change-signal precision
  and recall, alert precision and burden, forecast calibration, resolution
  coverage, and retraction behavior.
- Slice results by geography, language, source availability, event domain,
  authority class, and infrastructure coverage.  Blind publisher identity in
  symmetry tests where identity is not a legitimate feature.
- Store evaluation runs and gate promotion of fusion, change detection,
  prediction, and alert configurations on explicit thresholds.

**Acceptance:** replay is deterministic and cutoff-safe; the live DB remains
byte-for-byte unaffected; future source revisions cannot leak backward; critical
symmetry and false-alert regressions block promotion; reports expose missing
labels and weak geographic coverage rather than silently excluding them.

### 16. Enforce licensing, security, and workload limits end to end

**Outcome:** convert the existing local safeguards and source contracts into
system-wide, continuously tested enforcement suitable for sustained operation.

- Audit every source, derived dataset, map asset, and model service for license,
  attribution, allowed use, retention, redistribution, credential scope,
  geographic limits, and review date.  Disable sources whose contract is absent
  or expired.
- Centralize outbound network enforcement around connector allowlists, HTTPS,
  redirect validation, response-byte limits, timeouts, rate limits, backoff, and
  credential redaction.  Browser clients never receive provider credentials.
- Enforce per-source requests, bytes, items, retained versions, and disk use;
  per-engine batch and model-call budgets; bounded queues; and graceful load
  shedding that preserves high-priority evidence and forecast resolution.
- Apply retention and deletion rules to raw documents, private mail, tracks,
  caches, derived products, exports, backups, and logs while retaining only the
  audit artifacts permitted by the source contract.
- Harden loopback services with same-origin checks, CSRF protection for local
  writes, security headers, path validation, safe JSON limits, private database
  permissions, secret-file checks, and explicit rejection of remote binding when
  private data is enabled.
- Add operational health views and CI gates for stale policies, unbounded source
  access, secret leakage, migration safety, queue growth, disk projections, and
  license attribution.

**Acceptance:** adversarial connector, redirect, oversized-payload, secret-
redaction, retention, remote-binding, queue-flood, and disk-budget tests pass;
every rendered/exported datum has an applicable source policy; disabling a
source stops acquisition safely; overload degrades coverage explicitly instead
of silently dropping epistemic context.

## Dependency and delivery sequence

The numbered order is also the dependency order:

1. Steps 4 and 5 add contextual and movement layers without interpretation.
2. Step 6 establishes the stable fused event unit consumed downstream.
3. Step 7 grounds and correlates text-first reports before they can shape a
   regional baseline.
4. Steps 8 and 9 turn event history into bounded, evidence-linked change.
5. Steps 10 and 11 predict and calibrate only after fused events and baselines
   exist, while continuing to run in shadow mode.
6. Steps 12 and 13 expose the operational picture, briefings, and opt-in
   watchlists without delivery.
7. Step 14 crosses into Entity Core only through its existing policy-controlled
   delivery path.
8. Step 15 supplies promotion evidence, and step 16 makes all accumulated
   contracts and limits enforceable end to end.

Steps may add hidden schemas, shadow computation, fixture APIs, or engineering
dashboard diagnostics needed by later work.  They must not expose or activate a
later product behavior before that later step's acceptance tests pass.

## Non-negotiable epistemic rules

- Observation, report, inference, hypothesis, and forecast remain distinct.
- Repetition and syndication do not create independent corroboration.
- Proximity and temporal order do not establish causation.
- Movement tracks never imply hostile or criminal intent by themselves.
- Corrections, deletions, source versions, and evidence cutoffs are retained.
- Every conclusion and relationship carries provenance, method, and confidence.
- Missing coverage is represented as unknown, not as evidence of absence.
- Model calls are bounded and occur only after deterministic prioritization.

## Delivery rule

Each numbered step is delivered as a reviewable commit with migrations,
bounded backfills, tests, operational configuration, and rollback-safe database
handling where applicable. This checklist is updated only when its acceptance
tests pass.
