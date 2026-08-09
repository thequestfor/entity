"""Quota and audit wrapper for background intelligence model calls."""

import hashlib
from datetime import UTC, datetime

from agent.models.base import ModelUnavailable
from agent.intelligence.store import utc_now


class ReasoningBudget:
    def __init__(self, store, hourly_calls=24, daily_calls=200,
                 forecast_hourly_reserve=0, forecast_daily_reserve=0,
                 forecast_hourly_calls=None, forecast_daily_calls=None,
                 grounding_hourly_reserve=0, grounding_daily_reserve=0,
                 grounding_hourly_calls=None, grounding_daily_calls=None,
                 worldview_hourly_calls=None, worldview_daily_calls=None):
        self.store = store
        self.hourly_calls = max(1, int(hourly_calls))
        self.daily_calls = max(self.hourly_calls, int(daily_calls))
        self.policies = {
            "worldview": self._policy(
                worldview_hourly_calls or self.hourly_calls,
                worldview_daily_calls or self.daily_calls, 0, 0,
            ),
            "grounding": self._policy(
                grounding_hourly_calls or self.hourly_calls,
                grounding_daily_calls or self.daily_calls,
                grounding_hourly_reserve, grounding_daily_reserve,
            ),
            "forecast": self._policy(
                forecast_hourly_calls or self.hourly_calls,
                forecast_daily_calls or self.daily_calls,
                forecast_hourly_reserve, forecast_daily_reserve,
            ),
        }
        self._sync_policies()

    def _policy(self, hourly_limit, daily_limit, hourly_reserve, daily_reserve):
        return {
            "hourly_limit": max(1, min(self.hourly_calls, int(hourly_limit))),
            "daily_limit": max(1, min(self.daily_calls, int(daily_limit))),
            "hourly_reserve": max(0, min(self.hourly_calls, int(hourly_reserve))),
            "daily_reserve": max(0, min(self.daily_calls, int(daily_reserve))),
        }

    def _sync_policies(self):
        now = utc_now()
        with self.store._connect() as connection:
            connection.execute(
                """UPDATE intelligence_model_attempts
                   SET status='abandoned',error_code='ProcessInterrupted',
                       finished_at=?
                   WHERE status='reserved'
                     AND julianday(started_at)<julianday('now','-10 minutes')""",
                (now,),
            )
            for lane, policy in self.policies.items():
                connection.execute(
                    """INSERT INTO intelligence_budget_lane_policies (
                         lane,hourly_limit,daily_limit,hourly_reserve,daily_reserve,
                         configured_by,updated_at
                       ) VALUES (?,?,?,?,?,'runtime-configuration',?)
                       ON CONFLICT(lane) DO UPDATE SET
                         hourly_limit=excluded.hourly_limit,
                         daily_limit=excluded.daily_limit,
                         hourly_reserve=excluded.hourly_reserve,
                         daily_reserve=excluded.daily_reserve,
                         configured_by=excluded.configured_by,
                         updated_at=excluded.updated_at""",
                    (
                        lane, policy["hourly_limit"], policy["daily_limit"],
                        policy["hourly_reserve"], policy["daily_reserve"], now,
                    ),
                )

    def acquire(self, prompt, estimated_output_tokens=1000, lane="worldview",
                operation="model-call"):
        now = datetime.now(UTC)
        now_text = utc_now()
        hour = now.strftime("%Y-%m-%dT%H:00:00Z")
        day = now.strftime("%Y-%m-%dT00:00:00Z")
        prompt_text = str(prompt)
        input_tokens = max(1, len(prompt_text) // 4)
        input_hash = hashlib.sha256(prompt_text.encode()).hexdigest()
        policy = self.policies.get(
            lane, self._policy(self.hourly_calls, self.daily_calls, 0, 0)
        )
        denial = ""
        attempt_id = None
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            buckets = (
                ("hour", hour, self.hourly_calls, "hourly_limit", "hourly_reserve"),
                ("day", day, self.daily_calls, "daily_limit", "daily_reserve"),
            )
            for kind, start, total_limit, limit_key, reserve_key in buckets:
                used = self._usage(connection, kind, start)
                lane_used = self._lane_usage(connection, kind, start, lane)
                if used >= total_limit:
                    denial = f"Intelligence {kind}ly reasoning budget exhausted"
                    break
                if lane_used >= policy[limit_key]:
                    denial = f"Intelligence {lane} {kind}ly lane budget exhausted"
                    break
                other_reserve = sum(
                    max(0, item[reserve_key] - self._lane_usage(
                        connection, kind, start, other_lane
                    ))
                    for other_lane, item in self.policies.items()
                    if other_lane != lane
                )
                if used >= total_limit - other_reserve:
                    denial = (
                        f"Intelligence {kind}ly reserved lane capacity protected"
                    )
                    break
            status = "budget-denied" if denial else "reserved"
            attempt_id = connection.execute(
                """INSERT INTO intelligence_model_attempts (
                     lane,operation,input_hash,status,error_code,
                     estimated_input_tokens,estimated_output_tokens,started_at,
                     finished_at
                   ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    lane, str(operation or "model-call")[:120], input_hash,
                    status, "ModelUnavailable" if denial else "", input_tokens,
                    int(estimated_output_tokens), now_text,
                    now_text if denial else None,
                ),
            ).lastrowid
            if not denial:
                for kind, start, *_ in buckets:
                    connection.execute(
                        """INSERT INTO intelligence_budget_usage (
                             bucket_type,bucket_start,model_calls,
                             estimated_input_tokens,estimated_output_tokens,updated_at
                           ) VALUES (?,?,1,?,?,?)
                           ON CONFLICT(bucket_type,bucket_start) DO UPDATE SET
                             model_calls=model_calls+1,
                             estimated_input_tokens=estimated_input_tokens+
                               excluded.estimated_input_tokens,
                             estimated_output_tokens=estimated_output_tokens+
                               excluded.estimated_output_tokens,
                             updated_at=excluded.updated_at""",
                        (kind, start, input_tokens, estimated_output_tokens, now_text),
                    )
                    connection.execute(
                        """INSERT INTO intelligence_budget_lane_usage (
                             bucket_type,bucket_start,lane,model_calls,
                             estimated_input_tokens,estimated_output_tokens,updated_at
                           ) VALUES (?,?,?,1,?,?,?)
                           ON CONFLICT(bucket_type,bucket_start,lane) DO UPDATE SET
                             model_calls=model_calls+1,
                             estimated_input_tokens=estimated_input_tokens+
                               excluded.estimated_input_tokens,
                             estimated_output_tokens=estimated_output_tokens+
                               excluded.estimated_output_tokens,
                             updated_at=excluded.updated_at""",
                        (
                            kind, start, lane, input_tokens,
                            estimated_output_tokens, now_text,
                        ),
                    )
        if denial:
            raise ModelUnavailable(denial)
        return attempt_id

    def _usage(self, connection, kind, start):
        row = connection.execute(
            """SELECT model_calls FROM intelligence_budget_usage
               WHERE bucket_type=? AND bucket_start=?""", (kind, start)
        ).fetchone()
        return int(row[0] or 0) if row else 0

    def _lane_usage(self, connection, kind, start, lane):
        row = connection.execute(
            """SELECT model_calls FROM intelligence_budget_lane_usage
               WHERE bucket_type=? AND bucket_start=? AND lane=?""",
            (kind, start, lane),
        ).fetchone()
        return int(row[0] or 0) if row else 0

    def finish(self, attempt_id, status, provider="", error_code=""):
        if not attempt_id:
            return
        with self.store._connect() as connection:
            connection.execute(
                """UPDATE intelligence_model_attempts
                   SET status=?,provider=?,error_code=?,finished_at=? WHERE id=?""",
                (
                    str(status)[:40], str(provider or "")[:120],
                    str(error_code or "")[:120], utc_now(), int(attempt_id),
                ),
            )


class BudgetedModelRouter:
    def __init__(self, router, budget, lane="worldview"):
        self._router = router
        self.budget = budget
        self.lane = lane

    def __getattr__(self, name):
        return getattr(self._router, name)

    def for_lane(self, lane):
        return BudgetedModelRouter(self._router, self.budget, lane)

    def _provider_name(self):
        value = getattr(self._router, "last_provider_name", None)
        if value:
            return str(value)
        provider_name = getattr(self._router, "provider_name", None)
        if callable(provider_name):
            try:
                return str(provider_name() or "")
            except Exception:
                return ""
        return ""

    def generate_json(self, prompt, *args, **kwargs):
        operation = kwargs.pop("_budget_operation", None) or kwargs.get(
            "routing", "model-json"
        )
        attempt = self.budget.acquire(prompt, lane=self.lane, operation=operation)
        try:
            result = self._router.generate_json(prompt, *args, **kwargs)
        except Exception as exc:
            self.budget.finish(
                attempt, "failed", self._provider_name(), type(exc).__name__
            )
            raise
        if not isinstance(result, dict):
            self.budget.finish(
                attempt, "invalid-output", self._provider_name(), "NonObjectJSON"
            )
            raise ValueError("Model JSON response was not an object")
        self.budget.finish(attempt, "completed", self._provider_name())
        return result

    def generate(self, prompt, *args, **kwargs):
        operation = kwargs.pop("_budget_operation", None) or "model-text"
        attempt = self.budget.acquire(prompt, lane=self.lane, operation=operation)
        try:
            result = self._router.generate(prompt, *args, **kwargs)
            self.budget.finish(attempt, "completed", self._provider_name())
            return result
        except Exception as exc:
            self.budget.finish(
                attempt, "failed", self._provider_name(), type(exc).__name__
            )
            raise
