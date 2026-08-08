"""Quota wrapper for model JSON calls used by background intelligence."""

from datetime import UTC, datetime

from agent.models.base import ModelUnavailable
from agent.intelligence.store import utc_now


class ReasoningBudget:
    def __init__(self,store,hourly_calls=24,daily_calls=200):
        self.store=store; self.hourly_calls=max(1,int(hourly_calls)); self.daily_calls=max(self.hourly_calls,int(daily_calls))

    def acquire(self,prompt,estimated_output_tokens=1000):
        now=datetime.now(UTC); hour=now.strftime("%Y-%m-%dT%H:00:00Z"); day=now.strftime("%Y-%m-%dT00:00:00Z")
        input_tokens=max(1,len(str(prompt))//4)
        with self.store._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            for kind,start,limit in (("hour",hour,self.hourly_calls),("day",day,self.daily_calls)):
                row=c.execute("SELECT model_calls FROM intelligence_budget_usage WHERE bucket_type=? AND bucket_start=?",(kind,start)).fetchone()
                if row and int(row[0])>=limit: raise ModelUnavailable(f"Intelligence {kind}ly reasoning budget exhausted")
            for kind,start in (("hour",hour),("day",day)):
                c.execute("INSERT INTO intelligence_budget_usage (bucket_type,bucket_start,model_calls,estimated_input_tokens,estimated_output_tokens,updated_at) VALUES (?,?,1,?,?,?) ON CONFLICT(bucket_type,bucket_start) DO UPDATE SET model_calls=model_calls+1,estimated_input_tokens=estimated_input_tokens+excluded.estimated_input_tokens,estimated_output_tokens=estimated_output_tokens+excluded.estimated_output_tokens,updated_at=excluded.updated_at",
                          (kind,start,input_tokens,estimated_output_tokens,utc_now()))


class BudgetedModelRouter:
    def __init__(self,router,budget): self._router=router; self.budget=budget
    def __getattr__(self,name): return getattr(self._router,name)
    def generate_json(self,prompt,*args,**kwargs):
        self.budget.acquire(prompt)
        return self._router.generate_json(prompt,*args,**kwargs)
    def generate(self,prompt,*args,**kwargs):
        self.budget.acquire(prompt)
        return self._router.generate(prompt,*args,**kwargs)
