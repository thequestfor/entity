CREATE TABLE source_policies (
    source_id TEXT PRIMARY KEY,
    access_class TEXT NOT NULL,
    authority_class TEXT NOT NULL,
    evidence_role TEXT NOT NULL,
    license_name TEXT NOT NULL DEFAULT '',
    license_url TEXT NOT NULL DEFAULT '',
    attribution TEXT NOT NULL DEFAULT '',
    usage_scope TEXT NOT NULL DEFAULT 'review-required',
    credentials_required INTEGER NOT NULL DEFAULT 0,
    geographic_coverage TEXT NOT NULL DEFAULT 'unspecified',
    expected_latency TEXT NOT NULL DEFAULT 'unspecified',
    independence_family TEXT NOT NULL,
    allowed_hosts TEXT NOT NULL DEFAULT '[]',
    caveats TEXT NOT NULL DEFAULT '[]',
    retention_days INTEGER,
    policy_version TEXT NOT NULL,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
);

CREATE INDEX idx_source_policies_role
ON source_policies(evidence_role,authority_class);

CREATE TABLE source_contract_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    violations TEXT NOT NULL DEFAULT '[]',
    contract_snapshot TEXT NOT NULL DEFAULT '{}',
    checked_at TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
);

CREATE INDEX idx_source_contract_audits_source
ON source_contract_audits(source_id,checked_at DESC);
