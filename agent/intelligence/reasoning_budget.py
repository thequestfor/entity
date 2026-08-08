"""Quota wrapper for model JSON calls used by background intelligence."""

from datetime import UTC, datetime

from agent.models.base import ModelUnavailable
from agent.intelligence.store import utc_now


class ReasoningBudget:
    def __init__(self,store,hourly_calls=24,daily_calls=200,
                 forecast_hourly_reserve=0,forecast_daily_reserve=0,
                 forecast_hourly_calls=None,forecast_daily_calls=None):
        self.store=store; self.hourly_calls=max(1,int(hourly_calls)); self.daily_calls=max(self.hourly_calls,int(daily_calls))
        self.forecast_hourly_reserve=max(0,min(self.hourly_calls,int(forecast_hourly_reserve)))
        self.forecast_daily_reserve=max(0,min(self.daily_calls,int(forecast_daily_reserve)))
        self.forecast_hourly_calls=max(1,int(forecast_hourly_calls or self.hourly_calls))
        self.forecast_daily_calls=max(1,int(forecast_daily_calls or self.daily_calls))

    def acquire(self,prompt,estimated_output_tokens=1000,lane="worldview"):
        now=datetime.now(UTC); hour=now.strftime("%Y-%m-%dT%H:00:00Z"); day=now.strftime("%Y-%m-%dT00:00:00Z")
        input_tokens=max(1,len(str(prompt))//4)
        with self.store._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            buckets=(("hour",hour,self.hourly_calls,self.forecast_hourly_reserve,self.forecast_hourly_calls),("day",day,self.daily_calls,self.forecast_daily_reserve,self.forecast_daily_calls))
            for kind,start,limit,reserve,forecast_limit in buckets:
                row=c.execute("SELECT model_calls FROM intelligence_budget_usage WHERE bucket_type=? AND bucket_start=?",(kind,start)).fetchone()
                used=int(row[0] or 0) if row else 0
                lane_row=c.execute("SELECT model_calls FROM intelligence_budget_lane_usage WHERE bucket_type=? AND bucket_start=? AND lane=?",(kind,start,lane)).fetchone()
                lane_used=int(lane_row[0] or 0) if lane_row else 0
                forecast_row=c.execute("SELECT model_calls FROM intelligence_budget_lane_usage WHERE bucket_type=? AND bucket_start=? AND lane='forecast'",(kind,start)).fetchone()
                forecast_used=int(forecast_row[0] or 0) if forecast_row else 0
                if used>=limit: raise ModelUnavailable(f"Intelligence {kind}ly reasoning budget exhausted")
                if lane=="forecast" and lane_used>=forecast_limit:
                    raise ModelUnavailable(f"Intelligence forecast {kind}ly lane budget exhausted")
                remaining_reserve=max(0,reserve-forecast_used)
                if lane!="forecast" and used>=limit-remaining_reserve:
                    raise ModelUnavailable(f"Intelligence {kind}ly forecast reserve protected")
            for kind,start in (("hour",hour),("day",day)):
                c.execute("INSERT INTO intelligence_budget_usage (bucket_type,bucket_start,model_calls,estimated_input_tokens,estimated_output_tokens,updated_at) VALUES (?,?,1,?,?,?) ON CONFLICT(bucket_type,bucket_start) DO UPDATE SET model_calls=model_calls+1,estimated_input_tokens=estimated_input_tokens+excluded.estimated_input_tokens,estimated_output_tokens=estimated_output_tokens+excluded.estimated_output_tokens,updated_at=excluded.updated_at",
                          (kind,start,input_tokens,estimated_output_tokens,utc_now()))
                c.execute("INSERT INTO intelligence_budget_lane_usage (bucket_type,bucket_start,lane,model_calls,estimated_input_tokens,estimated_output_tokens,updated_at) VALUES (?,?,?,1,?,?,?) ON CONFLICT(bucket_type,bucket_start,lane) DO UPDATE SET model_calls=model_calls+1,estimated_input_tokens=estimated_input_tokens+excluded.estimated_input_tokens,estimated_output_tokens=estimated_output_tokens+excluded.estimated_output_tokens,updated_at=excluded.updated_at",
                          (kind,start,lane,input_tokens,estimated_output_tokens,utc_now()))


class BudgetedModelRouter:
    def __init__(self,router,budget,lane="worldview"): self._router=router; self.budget=budget; self.lane=lane
    def __getattr__(self,name): return getattr(self._router,name)
    def for_lane(self,lane): return BudgetedModelRouter(self._router,self.budget,lane)
    def generate_json(self,prompt,*args,**kwargs):
        self.budget.acquire(prompt,lane=self.lane)
        return self._router.generate_json(prompt,*args,**kwargs)
    def generate(self,prompt,*args,**kwargs):
        self.budget.acquire(prompt,lane=self.lane)
        return self._router.generate(prompt,*args,**kwargs)
