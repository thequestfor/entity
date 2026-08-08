-- Source observations remain immutable; this migration establishes the graph
-- vocabulary without performing semantic event fusion (roadmap step 6).
CREATE TABLE world_entities (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    country_code TEXT NOT NULL DEFAULT '',
    identifiers TEXT NOT NULL DEFAULT '{}',
    properties TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 0.5,
    first_seen_at TEXT,
    last_seen_at TEXT,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_world_entities_type_name
ON world_entities(entity_type,canonical_name);

CREATE TABLE world_entity_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT '',
    source_id TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    UNIQUE(entity_id,normalized_alias,language,source_id),
    FOREIGN KEY(entity_id) REFERENCES world_entities(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE SET NULL
);

CREATE INDEX idx_world_alias_lookup
ON world_entity_aliases(normalized_alias,language);

CREATE TABLE world_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    severity REAL NOT NULL DEFAULT 0.0,
    confidence REAL NOT NULL DEFAULT 0.5,
    latitude REAL,
    longitude REAL,
    geometry TEXT NOT NULL DEFAULT '{}',
    country_code TEXT NOT NULL DEFAULT '',
    country_name TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    ended_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    source_count INTEGER NOT NULL DEFAULT 0,
    observation_count INTEGER NOT NULL DEFAULT 0,
    situation_id TEXT UNIQUE,
    geo_feature_id TEXT UNIQUE,
    properties TEXT NOT NULL DEFAULT '{}',
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE SET NULL,
    FOREIGN KEY(geo_feature_id) REFERENCES geo_features(id) ON DELETE SET NULL
);

CREATE INDEX idx_world_events_viewport
ON world_events(status,event_type,last_seen_at DESC,latitude,longitude);
CREATE INDEX idx_world_events_country
ON world_events(country_name,status,last_seen_at DESC);

CREATE TABLE world_event_observations (
    id TEXT PRIMARY KEY,
    world_event_id TEXT,
    document_version_id INTEGER NOT NULL,
    document_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    observation_kind TEXT NOT NULL,
    occurred_at TEXT,
    published_at TEXT,
    captured_at TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    geometry TEXT NOT NULL DEFAULT '{}',
    payload_hash TEXT NOT NULL,
    properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(document_version_id,world_event_id),
    FOREIGN KEY(world_event_id) REFERENCES world_events(id) ON DELETE SET NULL,
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES sources(id)
);

CREATE INDEX idx_world_observations_event_time
ON world_event_observations(world_event_id,captured_at DESC);
CREATE INDEX idx_world_observations_source_time
ON world_event_observations(source_id,captured_at DESC);

CREATE TABLE world_event_relations (
    id TEXT PRIMARY KEY,
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_kind TEXT NOT NULL,
    object_id TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    causal_status TEXT NOT NULL DEFAULT 'noncausal',
    evidence_count INTEGER NOT NULL DEFAULT 0,
    evidence TEXT NOT NULL DEFAULT '[]',
    valid_from TEXT,
    valid_until TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(subject_kind,subject_id,predicate,object_kind,object_id,method)
);

CREATE INDEX idx_world_relations_subject
ON world_event_relations(subject_kind,subject_id,predicate,status);
CREATE INDEX idx_world_relations_object
ON world_event_relations(object_kind,object_id,predicate,status);

CREATE TABLE infrastructure_assets (
    id TEXT PRIMARY KEY,
    asset_type TEXT NOT NULL,
    name TEXT NOT NULL,
    operator_entity_id TEXT,
    country_code TEXT NOT NULL DEFAULT '',
    country_name TEXT NOT NULL DEFAULT '',
    latitude REAL,
    longitude REAL,
    geometry TEXT NOT NULL DEFAULT '{}',
    identifiers TEXT NOT NULL DEFAULT '{}',
    properties TEXT NOT NULL DEFAULT '{}',
    source_id TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    observed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(operator_entity_id) REFERENCES world_entities(id) ON DELETE SET NULL,
    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE SET NULL
);

CREATE INDEX idx_infrastructure_viewport
ON infrastructure_assets(asset_type,latitude,longitude);

CREATE TABLE movement_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    track_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    altitude_m REAL,
    speed_mps REAL,
    heading_degrees REAL,
    source_id TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(entity_id,track_type,observed_at,source_id),
    FOREIGN KEY(entity_id) REFERENCES world_entities(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES sources(id)
);

CREATE INDEX idx_movement_tracks_entity_time
ON movement_tracks(entity_id,observed_at DESC);

CREATE TABLE regional_baselines (
    id TEXT PRIMARY KEY,
    region_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    season_bucket TEXT NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    expected_rate REAL NOT NULL DEFAULT 0.0,
    dispersion REAL NOT NULL DEFAULT 0.0,
    confidence REAL NOT NULL DEFAULT 0.0,
    feature_version TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(region_key,event_type,season_bucket,feature_version)
);

CREATE TABLE world_change_signals (
    id TEXT PRIMARY KEY,
    world_event_id TEXT,
    region_key TEXT NOT NULL DEFAULT '',
    signal_type TEXT NOT NULL,
    expected_value REAL,
    observed_value REAL,
    score REAL NOT NULL,
    confidence REAL NOT NULL,
    evidence TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    detected_at TEXT NOT NULL,
    expires_at TEXT,
    method TEXT NOT NULL,
    FOREIGN KEY(world_event_id) REFERENCES world_events(id) ON DELETE CASCADE
);

CREATE INDEX idx_world_change_signals_active
ON world_change_signals(status,score DESC,detected_at DESC);

CREATE TABLE world_watchlists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '{}',
    priority REAL NOT NULL DEFAULT 0.5,
    enabled INTEGER NOT NULL DEFAULT 1,
    notify INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE world_alerts (
    id TEXT PRIMARY KEY,
    watchlist_id TEXT,
    world_event_id TEXT,
    change_signal_id TEXT,
    severity REAL NOT NULL,
    confidence REAL NOT NULL,
    headline TEXT NOT NULL,
    rationale TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    acknowledged_at TEXT,
    cooldown_key TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(watchlist_id) REFERENCES world_watchlists(id) ON DELETE SET NULL,
    FOREIGN KEY(world_event_id) REFERENCES world_events(id) ON DELETE SET NULL,
    FOREIGN KEY(change_signal_id) REFERENCES world_change_signals(id) ON DELETE SET NULL
);

CREATE INDEX idx_world_alerts_delivery
ON world_alerts(status,severity DESC,created_at);

CREATE TABLE world_graph_backfill_state (
    lane TEXT PRIMARY KEY,
    cursor_id INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    created_count INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
