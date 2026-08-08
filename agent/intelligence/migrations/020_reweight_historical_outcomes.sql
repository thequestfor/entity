-- Historical rows predate explicit evidence-basis weights. Preserve their
-- audit records while materializing conservative weights for future Bayesian
-- recalculation; cross-source agreement is not equivalent to ground truth.
UPDATE publisher_claim_outcomes
SET evidence_basis='independent-family-corroboration',outcome_weight=.55
WHERE method='truth-maintenance-v1';

UPDATE publisher_claim_outcomes
SET evidence_basis='corroboration',outcome_weight=.50
WHERE method='verification-result-v1';

UPDATE intelligence_feature_gates
SET reason='Awaiting 100 training forecasts, 30 out-of-time validation forecasts, and safe improvement'
WHERE feature='learned_ensemble' AND status='blocked';
