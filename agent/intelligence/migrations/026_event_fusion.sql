-- Canonical event fusion is additive: source documents, situations, and prior
-- world-event projections remain immutable/auditable inputs.
ALTER TABLE world_event_observations ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE world_event_observations ADD COLUMN predecessor_observation_id TEXT;
ALTER TABLE world_event_observations ADD COLUMN reporting_family_key TEXT NOT NULL DEFAULT '';
ALTER TABLE world_event_observations ADD COLUMN source_policy_version TEXT NOT NULL DEFAULT '';
ALTER TABLE world_event_observations ADD COLUMN occurred_precision_seconds INTEGER;

ALTER TABLE world_events ADD COLUMN independent_family_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE world_events ADD COLUMN contradiction_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE world_events ADD COLUMN freshness TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE world_events ADD COLUMN current_version_id INTEGER;

CREATE TABLE world_event_fusion_decisions (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL,
    candidate_event_id TEXT NOT NULL DEFAULT '',
    chosen_event_id TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0.0,
    components TEXT NOT NULL DEFAULT '{}',
    vetoes TEXT NOT NULL DEFAULT '[]',
    cutoff_at TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    method TEXT NOT NULL,
    model_involvement TEXT NOT NULL DEFAULT 'none',
    created_at TEXT NOT NULL,
    FOREIGN KEY(observation_id) REFERENCES world_event_observations(id)
);

CREATE INDEX idx_fusion_decisions_observation
ON world_event_fusion_decisions(observation_id,outcome,created_at);

CREATE TABLE world_event_memberships (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL,
    world_event_id TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    decision_id TEXT,
    action TEXT NOT NULL,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(observation_id) REFERENCES world_event_observations(id),
    FOREIGN KEY(world_event_id) REFERENCES world_events(id),
    FOREIGN KEY(decision_id) REFERENCES world_event_fusion_decisions(id)
);

CREATE UNIQUE INDEX idx_event_membership_one_active
ON world_event_memberships(observation_id) WHERE active=1;
CREATE INDEX idx_event_membership_event_active
ON world_event_memberships(world_event_id,active,observation_id);

CREATE TABLE world_event_aliases (
    alias_event_id TEXT PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    operation_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(alias_event_id) REFERENCES world_events(id),
    FOREIGN KEY(canonical_event_id) REFERENCES world_events(id)
);

CREATE INDEX idx_event_alias_canonical
ON world_event_aliases(canonical_event_id,status);

CREATE TABLE world_event_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    world_event_id TEXT NOT NULL,
    version_hash TEXT NOT NULL,
    membership_hash TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    method TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(world_event_id,version_hash),
    FOREIGN KEY(world_event_id) REFERENCES world_events(id)
);

CREATE INDEX idx_event_versions_event
ON world_event_versions(world_event_id,id DESC);

CREATE TABLE world_event_fusion_reviews (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL,
    candidate_event_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    score REAL NOT NULL,
    rationale TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution_operation_id TEXT,
    FOREIGN KEY(observation_id) REFERENCES world_event_observations(id),
    FOREIGN KEY(candidate_event_id) REFERENCES world_events(id),
    FOREIGN KEY(decision_id) REFERENCES world_event_fusion_decisions(id)
);

CREATE INDEX idx_fusion_reviews_status
ON world_event_fusion_reviews(status,score DESC,created_at);

CREATE TABLE world_event_operations (
    id TEXT PRIMARY KEY,
    operation_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'applied',
    before_snapshot TEXT NOT NULL DEFAULT '{}',
    after_snapshot TEXT NOT NULL DEFAULT '{}',
    rationale TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reversed_at TEXT,
    reverse_operation_id TEXT
);

CREATE TABLE world_event_fusion_constraints (
    left_event_id TEXT NOT NULL,
    right_event_id TEXT NOT NULL,
    constraint_type TEXT NOT NULL,
    operation_id TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    PRIMARY KEY(left_event_id,right_event_id,constraint_type),
    FOREIGN KEY(left_event_id) REFERENCES world_events(id),
    FOREIGN KEY(right_event_id) REFERENCES world_events(id)
);

CREATE TABLE world_event_fusion_state (
    lane TEXT PRIMARY KEY,
    cursor_version_id INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    linked INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL DEFAULT 0,
    reviews INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
