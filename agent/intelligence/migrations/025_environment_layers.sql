-- Weather forecasts and infrastructure references remain contextual layers.
-- They are never factual event corroboration or evidence of operating status.
CREATE TABLE weather_forecast_cells (
    source_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    valid_at TEXT NOT NULL,
    document_id TEXT NOT NULL,
    document_version_id INTEGER NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    grid_key TEXT NOT NULL,
    forecast_run_at TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    temperature_c REAL,
    precipitation_mm REAL,
    wind_speed_kph REAL,
    wind_gust_kph REAL,
    pressure_hpa REAL,
    weather_code INTEGER,
    units TEXT NOT NULL DEFAULT '{}',
    properties TEXT NOT NULL DEFAULT '{}',
    expires_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(source_id, external_id, valid_at),
    FOREIGN KEY(source_id) REFERENCES sources(id),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id)
);

CREATE INDEX idx_weather_forecast_viewport
ON weather_forecast_cells(valid_at,latitude,longitude);

CREATE INDEX idx_weather_forecast_expiry
ON weather_forecast_cells(expires_at,valid_at);

CREATE TABLE weather_forecast_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    valid_at TEXT NOT NULL,
    document_version_id INTEGER NOT NULL,
    forecast_run_at TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    forecast TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(document_version_id,valid_at),
    FOREIGN KEY(source_id) REFERENCES sources(id),
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id)
);

CREATE INDEX idx_weather_versions_cell_time
ON weather_forecast_versions(source_id,external_id,valid_at,captured_at DESC);

ALTER TABLE infrastructure_assets ADD COLUMN external_id TEXT NOT NULL DEFAULT '';
ALTER TABLE infrastructure_assets ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE infrastructure_assets ADD COLUMN document_id TEXT;
ALTER TABLE infrastructure_assets ADD COLUMN document_version_id INTEGER;
ALTER TABLE infrastructure_assets ADD COLUMN source_updated_at TEXT;
ALTER TABLE infrastructure_assets ADD COLUMN retired_at TEXT;

CREATE UNIQUE INDEX idx_infrastructure_source_external
ON infrastructure_assets(source_id,external_id)
WHERE source_id IS NOT NULL AND external_id != '';

CREATE INDEX idx_infrastructure_status_viewport
ON infrastructure_assets(status,asset_type,latitude,longitude);

CREATE TABLE infrastructure_asset_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    document_version_id INTEGER NOT NULL,
    snapshot TEXT NOT NULL DEFAULT '{}',
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(asset_id,document_version_id),
    FOREIGN KEY(asset_id) REFERENCES infrastructure_assets(id) ON DELETE CASCADE,
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id)
);

CREATE TABLE environment_layer_state (
    lane TEXT PRIMARY KEY,
    cursor_version_id INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    materialized INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
