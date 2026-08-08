-- Native geospatial observations are distinct from interpreted situations.
-- Forecast snapshots reference only observations available before cutoff.
CREATE TABLE geo_features (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    situation_id TEXT,
    feature_type TEXT NOT NULL,
    geometry_type TEXT NOT NULL DEFAULT 'Point',
    geometry TEXT NOT NULL DEFAULT '{}',
    centroid_latitude REAL,
    centroid_longitude REAL,
    bbox_west REAL,
    bbox_south REAL,
    bbox_east REAL,
    bbox_north REAL,
    grid_key TEXT NOT NULL DEFAULT '',
    country_code TEXT NOT NULL DEFAULT '',
    country_name TEXT NOT NULL DEFAULT '',
    severity REAL NOT NULL DEFAULT 0.0,
    severity_label TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.5,
    authoritative INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    started_at TEXT,
    observed_at TEXT NOT NULL,
    expires_at TEXT,
    properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_id, external_id),
    FOREIGN KEY(source_id) REFERENCES sources(id),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE SET NULL
);

CREATE INDEX idx_geo_features_viewport
ON geo_features(feature_type,status,observed_at DESC,centroid_latitude,centroid_longitude);
CREATE INDEX idx_geo_features_country
ON geo_features(country_name,status,observed_at DESC);
CREATE INDEX idx_geo_features_situation
ON geo_features(situation_id,observed_at DESC);

CREATE TABLE geo_feature_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_id TEXT NOT NULL,
    document_version_id INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    severity REAL NOT NULL DEFAULT 0.0,
    confidence REAL NOT NULL DEFAULT 0.5,
    geometry TEXT NOT NULL DEFAULT '{}',
    properties TEXT NOT NULL DEFAULT '{}',
    observation_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(feature_id, observation_hash),
    FOREIGN KEY(feature_id) REFERENCES geo_features(id) ON DELETE CASCADE,
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id)
);

CREATE INDEX idx_geo_observations_feature_time
ON geo_feature_observations(feature_id,observed_at DESC);

CREATE TABLE geo_cells (
    cell_key TEXT NOT NULL,
    feature_type TEXT NOT NULL,
    window_start TEXT NOT NULL,
    detection_count INTEGER NOT NULL DEFAULT 0,
    max_severity REAL NOT NULL DEFAULT 0.0,
    average_confidence REAL NOT NULL DEFAULT 0.0,
    centroid_latitude REAL NOT NULL,
    centroid_longitude REAL NOT NULL,
    latest_observed_at TEXT NOT NULL,
    properties TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY(cell_key,feature_type,window_start)
);

CREATE INDEX idx_geo_cells_viewport
ON geo_cells(feature_type,latest_observed_at DESC,centroid_latitude,centroid_longitude);

CREATE TABLE geospatial_backfill_state (
    name TEXT PRIMARY KEY,
    cursor_version_id INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    features_created INTEGER NOT NULL DEFAULT 0,
    observations_created INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE country_profiles (
    country_key TEXT PRIMARY KEY,
    country_code TEXT NOT NULL DEFAULT '',
    country_name TEXT NOT NULL,
    active_situations INTEGER NOT NULL DEFAULT 0,
    contested_situations INTEGER NOT NULL DEFAULT 0,
    active_hazards INTEGER NOT NULL DEFAULT 0,
    anomaly_count INTEGER NOT NULL DEFAULT 0,
    forecast_count INTEGER NOT NULL DEFAULT 0,
    average_confidence REAL NOT NULL DEFAULT 0.0,
    dimensions TEXT NOT NULL DEFAULT '{}',
    coverage_gaps TEXT NOT NULL DEFAULT '[]',
    method TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE country_profile_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    country_key TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE(country_key,snapshot_hash),
    FOREIGN KEY(country_key) REFERENCES country_profiles(country_key) ON DELETE CASCADE
);

CREATE TABLE geo_anomalies (
    id TEXT PRIMARY KEY,
    feature_id TEXT,
    situation_id TEXT,
    country_key TEXT NOT NULL DEFAULT '',
    anomaly_type TEXT NOT NULL,
    expected_value REAL,
    observed_value REAL,
    anomaly_score REAL NOT NULL,
    severity REAL NOT NULL,
    confidence REAL NOT NULL,
    evidence TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT,
    alert_emitted_at TEXT,
    method TEXT NOT NULL,
    FOREIGN KEY(feature_id) REFERENCES geo_features(id) ON DELETE CASCADE,
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE SET NULL
);

CREATE INDEX idx_geo_anomalies_active
ON geo_anomalies(status,severity DESC,last_seen_at DESC);

CREATE TABLE regional_assessments (
    id TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL UNIQUE,
    bbox TEXT NOT NULL,
    layers TEXT NOT NULL,
    since_at TEXT,
    headline TEXT NOT NULL,
    assessment TEXT NOT NULL,
    uncertainties TEXT NOT NULL DEFAULT '[]',
    evidence TEXT NOT NULL DEFAULT '[]',
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE forecast_geo_feature_snapshots (
    forecast_id TEXT PRIMARY KEY,
    situation_id TEXT NOT NULL,
    evidence_cutoff_at TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    features TEXT NOT NULL,
    feature_ids TEXT NOT NULL DEFAULT '[]',
    snapshot_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(forecast_id) REFERENCES forecasts(id) ON DELETE CASCADE,
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE
);

CREATE INDEX idx_forecast_geo_snapshot_cutoff
ON forecast_geo_feature_snapshots(evidence_cutoff_at,situation_id);
