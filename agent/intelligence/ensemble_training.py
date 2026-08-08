"""Leakage-resistant training and shadow promotion for forecast calibration."""

import json
import math
from dataclasses import dataclass
from uuid import uuid4

from agent.intelligence.store import utc_now


FEATURES = (
    "intercept", "base_rate_logit", "hypothesis_logit", "reasoning_logit",
    "family_count_log", "corroborated_ratio", "disputed_ratio"
)


@dataclass(frozen=True)
class TrainingResult:
    outcome: str = "not_ready"
    model_version_id: str = ""
    training_samples: int = 0
    validation_samples: int = 0
    promoted: bool = False
    reason: str = ""


class EnsembleTrainer:
    method = "regularized-logistic-calibration-v1"

    def __init__(self, store, enabled=True, minimum_samples=100,
                 minimum_validation=30):
        self.store = store
        self.enabled = bool(enabled)
        self.minimum_samples = max(50, int(minimum_samples))
        self.minimum_validation = max(20, int(minimum_validation))

    def train_if_ready(self):
        if not self.enabled:
            return TrainingResult(reason="Training disabled")
        samples = self._samples()
        if len(samples) < self.minimum_samples + self.minimum_validation:
            return TrainingResult(
                reason=(f"Awaiting {self.minimum_samples + self.minimum_validation} "
                        "high-confidence resolved V2 forecasts")
            )
        train, validation = self._out_of_time_split(samples)
        if len(train) < self.minimum_samples or len(validation) < self.minimum_validation:
            return TrainingResult(
                training_samples=len(train), validation_samples=len(validation),
                reason="Out-of-time situation-grouped split is not mature"
            )
        cutoff = max(item["created_at"] for item in train)
        with self.store._connect() as connection:
            prior = connection.execute(
                "SELECT 1 FROM ensemble_training_runs WHERE training_cutoff_at=?",
                (cutoff,)
            ).fetchone()
        if prior:
            return TrainingResult(
                training_samples=len(train), validation_samples=len(validation),
                reason="This immutable training cutoff was already evaluated"
            )
        coefficients = _fit([item["x"] for item in train],
                            [item["y"] for item in train])
        candidate = [_predict(coefficients, item["x"]) for item in validation]
        baseline = [item["baseline"] for item in validation]
        outcomes = [item["y"] for item in validation]
        candidate_metrics = _metrics(candidate, outcomes)
        baseline_metrics = _metrics(baseline, outcomes)
        subgroup_delta = self._worst_subgroup_delta(
            validation, candidate, baseline
        )
        critical_ok = self._latest_evaluation_passed()
        promoted = (
            critical_ok
            and baseline_metrics["brier"]-candidate_metrics["brier"] >= .005
            and candidate_metrics["log_loss"] <= baseline_metrics["log_loss"]+.001
            and candidate_metrics["ece"] <= max(
                .08, baseline_metrics["ece"]+.01
            )
            and subgroup_delta <= .03
        )
        reason = (
            "Candidate passed out-of-time calibration gates"
            if promoted else
            "Candidate did not safely outperform the fixed ensemble"
        )
        model_id = str(uuid4())
        now = utc_now()
        artifact = {
            "features": FEATURES, "coefficients": coefficients,
            "candidate_metrics": candidate_metrics,
            "baseline_metrics": baseline_metrics,
            "worst_subgroup_brier_delta": subgroup_delta,
            "constraints": {"component_coefficients_nonnegative": True,
                            "probability_bounds": [.05, .95]}
        }
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if promoted:
                connection.execute(
                    "UPDATE forecast_model_versions SET status='archived' "
                    "WHERE status='shadow'"
                )
            connection.execute(
                """
                INSERT INTO forecast_model_versions (
                  id,method,coefficients,sample_count,training_cutoff_at,status,
                  brier_score,log_loss,created_at,promoted_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (model_id, self.method, self.store._json(artifact), len(train),
                 cutoff, "shadow" if promoted else "rejected",
                 candidate_metrics["brier"], candidate_metrics["log_loss"],
                 now, now if promoted else None)
            )
            connection.execute(
                """
                INSERT INTO ensemble_training_runs (
                  model_version_id,training_cutoff_at,training_samples,
                  validation_samples,baseline_brier,candidate_brier,promoted,
                  reason,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (model_id, cutoff, len(train), len(validation),
                 baseline_metrics["brier"], candidate_metrics["brier"],
                 int(promoted), reason, now)
            )
            connection.execute(
                """
                UPDATE intelligence_feature_gates SET status=?,reason=?,
                  sample_count=?,metric=?,required_metric=.005,updated_at=?
                WHERE feature='learned_ensemble'
                """,
                ("shadow" if promoted else "blocked", reason, len(samples),
                 round(baseline_metrics["brier"]-candidate_metrics["brier"], 6),
                 now)
            )
        return TrainingResult(
            "trained", model_id, len(train), len(validation), promoted, reason
        )

    def _samples(self):
        with self.store._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM forecasts
                WHERE method='hypothesis-forecast-v2' AND status='resolved'
                  AND actual_outcome IS NOT NULL AND resolution_confidence>=.7
                ORDER BY created_at,id
                """
            ).fetchall()
            samples = []
            for row in rows:
                components = {
                    item["component"]: float(item["probability"])
                    for item in connection.execute(
                        "SELECT component,probability FROM "
                        "forecast_component_predictions WHERE forecast_id=?",
                        (row["id"],)
                    )
                }
                if not {"base_rate", "hypothesis", "reasoning"} <= components.keys():
                    continue
                try:
                    evidence = json.loads(row["evidence"] or "[]")
                except (TypeError, ValueError):
                    evidence = []
                families = len({
                    str(item.get("independence_key") or item.get("source_id") or "")
                    for item in evidence if isinstance(item, dict)
                }-{""})
                snapshot = connection.execute(
                    """
                    SELECT features FROM situation_feature_snapshots
                    WHERE situation_id=? AND observed_at<=?
                    ORDER BY observed_at DESC LIMIT 1
                    """, (row["situation_id"], row["created_at"])
                ).fetchone()
                try:
                    features = json.loads(snapshot["features"] or "{}") if snapshot else {}
                except (TypeError, ValueError):
                    features = {}
                claims = max(1, int(features.get("corroborated", 0))
                             + int(features.get("disputed", 0)))
                x = [1.0, _logit(components["base_rate"]),
                     _logit(components["hypothesis"]),
                     _logit(components["reasoning"]), math.log1p(families),
                     int(features.get("corroborated", 0))/claims,
                     int(features.get("disputed", 0))/claims]
                samples.append({"id": row["id"],
                                "situation_id": row["situation_id"],
                                "created_at": row["created_at"],
                                "category": row["category"],
                                "horizon": row["horizon_bucket"], "x": x,
                                "y": int(row["actual_outcome"]),
                                "baseline": float(row["ensemble_probability"]
                                                  or row["probability"])})
        return samples

    def _out_of_time_split(self, samples):
        validation = samples[-self.minimum_validation:]
        validation_situations = {item["situation_id"] for item in validation}
        train = [item for item in samples[:-self.minimum_validation]
                 if item["situation_id"] not in validation_situations]
        return train, validation

    def _worst_subgroup_delta(self, samples, candidate, baseline):
        groups = {}
        for item, candidate_p, baseline_p in zip(samples, candidate, baseline):
            for key in (("category", item["category"]),
                        ("horizon", item["horizon"])):
                groups.setdefault(key, []).append((item["y"], candidate_p, baseline_p))
        deltas = [
            sum((candidate_p-y)**2-(baseline_p-y)**2
                for y, candidate_p, baseline_p in values)/len(values)
            for values in groups.values() if len(values) >= 10
        ]
        return max(deltas, default=0.0)

    def _latest_evaluation_passed(self):
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT outcome,critical_failures FROM intelligence_evaluation_runs "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return bool(row and row["outcome"] == "passed"
                    and int(row["critical_failures"] or 0) == 0)


def _fit(features, outcomes, iterations=800, learning_rate=.025, l2=.04):
    coefficients = [0.0 for _ in FEATURES]
    count = max(1, len(features))
    for _ in range(iterations):
        gradients = [0.0 for _ in coefficients]
        for x, outcome in zip(features, outcomes):
            error = _predict_raw(coefficients, x)-outcome
            for index, value in enumerate(x):
                gradients[index] += error*value
        for index in range(len(coefficients)):
            penalty = 0.0 if index == 0 else l2*coefficients[index]
            coefficients[index] -= learning_rate*(gradients[index]/count+penalty)
            if 1 <= index <= 3:
                coefficients[index] = max(0.0, min(3.0, coefficients[index]))
            else:
                coefficients[index] = max(-3.0, min(3.0, coefficients[index]))
    return [round(value, 8) for value in coefficients]


def _predict(coefficients, features):
    return max(.05, min(.95, _predict_raw(coefficients, features)))


def _predict_raw(coefficients, features):
    value = sum(coefficient*feature
                for coefficient, feature in zip(coefficients, features))
    if value >= 0:
        return 1/(1+math.exp(-min(value, 30)))
    exponential = math.exp(max(value, -30))
    return exponential/(1+exponential)


def _logit(probability):
    probability = max(.01, min(.99, float(probability)))
    return math.log(probability/(1-probability))


def _metrics(probabilities, outcomes):
    count = max(1, len(outcomes))
    brier = sum((probability-outcome)**2
                for probability, outcome in zip(probabilities, outcomes))/count
    log_loss = -sum(
        outcome*math.log(max(1e-6, probability))
        +(1-outcome)*math.log(max(1e-6, 1-probability))
        for probability, outcome in zip(probabilities, outcomes)
    )/count
    buckets = {}
    for probability, outcome in zip(probabilities, outcomes):
        key=min(9, int(probability*10))
        buckets.setdefault(key, []).append((probability, outcome))
    ece = sum(
        len(values)/count*abs(
            sum(item[0] for item in values)/len(values)
            -sum(item[1] for item in values)/len(values)
        ) for values in buckets.values()
    )
    return {"brier": round(brier, 8), "log_loss": round(log_loss, 8),
            "ece": round(ece, 8)}
