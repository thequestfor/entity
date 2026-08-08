-- Geographic fields are evidence-derived.  They are deliberately separate
-- from a source document's raw coordinates so a later report cannot silently
-- move an established situation without recording disagreement.
ALTER TABLE situations ADD COLUMN location_country_code TEXT NOT NULL DEFAULT '';
ALTER TABLE situations ADD COLUMN location_country_name TEXT NOT NULL DEFAULT '';
ALTER TABLE situations ADD COLUMN location_label TEXT NOT NULL DEFAULT '';
ALTER TABLE situations ADD COLUMN location_precision_km REAL;
ALTER TABLE situations ADD COLUMN location_confidence REAL NOT NULL DEFAULT 0.0;
ALTER TABLE situations ADD COLUMN location_evidence_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE situations ADD COLUMN location_disagreement_km REAL NOT NULL DEFAULT 0.0;
ALTER TABLE situations ADD COLUMN location_method TEXT NOT NULL DEFAULT '';
ALTER TABLE situations ADD COLUMN location_updated_at TEXT;

CREATE INDEX idx_situations_country_updated
ON situations(location_country_code, updated_at DESC);

-- This is a current-state cache, not an intelligence source: aircraft never
-- become documents, claims, situations, or evidence for predictions.
CREATE TABLE aircraft_states (
    icao24 TEXT PRIMARY KEY,
    callsign TEXT NOT NULL DEFAULT '',
    origin_country TEXT NOT NULL DEFAULT '',
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    altitude_m REAL,
    velocity_mps REAL,
    heading_degrees REAL,
    vertical_rate_mps REAL,
    on_ground INTEGER NOT NULL DEFAULT 0,
    last_contact_at TEXT,
    observed_at TEXT NOT NULL,
    source_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_aircraft_states_observed
ON aircraft_states(observed_at DESC);
