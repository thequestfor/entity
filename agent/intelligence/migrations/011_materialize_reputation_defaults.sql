-- Materialize fields appended by migration 006 for legacy rows. This mirrors
-- migration 010 and removes false non-null integrity failures on older DBs.
UPDATE publisher_outcomes SET
    evidence_document_ids = COALESCE(evidence_document_ids, '[]'),
    outcome_confidence = COALESCE(outcome_confidence, 0.5),
    was_early = COALESCE(was_early, 0),
    verification_method = COALESCE(
        verification_method, 'delayed-corroboration-v2'
    );

UPDATE publisher_reputation SET
    reliability_lower_bound = COALESCE(reliability_lower_bound, 0.0),
    reliability_upper_bound = COALESCE(reliability_upper_bound, 1.0);
