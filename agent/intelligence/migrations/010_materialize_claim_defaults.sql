-- SQLite can expose ALTER TABLE defaults while legacy records still contain
-- no physical value for the appended fields. Rewrite the new fields once so
-- integrity checks and future SQLite versions see the same non-null values.
UPDATE claims SET
    attributed_to = COALESCE(attributed_to, ''),
    endorsement = COALESCE(endorsement, 'asserts'),
    extraction_confidence = COALESCE(extraction_confidence, 0.5),
    extraction_method = COALESCE(extraction_method, 'legacy'),
    extraction_version = COALESCE(extraction_version, 'legacy-v1'),
    precision = COALESCE(precision, 'unknown'),
    evidence_role = COALESCE(evidence_role, 'secondary');
