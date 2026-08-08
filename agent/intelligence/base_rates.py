import math

from agent.intelligence.store import utc_now


def horizon_bucket(created_at, target_at):
    from datetime import datetime
    start=datetime.fromisoformat(str(created_at).replace("Z","+00:00"))
    end=datetime.fromisoformat(str(target_at).replace("Z","+00:00"))
    hours=max(0,(end-start).total_seconds()/3600)
    if hours <= 24: return "0-1d"
    if hours <= 72: return "1-3d"
    if hours <= 168: return "3-7d"
    return "7-30d"


class BaseRateEngine:
    method="hierarchical-base-rate-v1"

    def __init__(self,store,prior_successes=1,prior_failures=1):
        self.store=store; self.prior_successes=prior_successes; self.prior_failures=prior_failures

    def estimate(self,category,kind,horizon):
        with self.store._connect() as c:
            row=c.execute("SELECT successes,failures,rate FROM base_rate_models WHERE category=? AND forecast_kind=? AND horizon_bucket=?",
                          (category,kind,horizon)).fetchone()
            if row: return float(row["rate"]),f"{category}:{kind}:{horizon}"
            row=c.execute("SELECT SUM(actual_outcome) yes,COUNT(*) n FROM forecasts WHERE actual_outcome IS NOT NULL AND category=?",
                          (category,)).fetchone()
        if row and row["n"]:
            return (float(row["yes"])+self.prior_successes)/(int(row["n"])+self.prior_successes+self.prior_failures),f"category:{category}"
        return .5,"uninformative-prior"

    def refresh(self):
        now=utc_now(); updated=0
        with self.store._connect() as c:
            rows=c.execute("SELECT category,forecast_kind,horizon_bucket,SUM(actual_outcome) yes,COUNT(*) n FROM forecasts WHERE actual_outcome IS NOT NULL GROUP BY category,forecast_kind,horizon_bucket").fetchall()
            for row in rows:
                success=int(row["yes"] or 0); failure=int(row["n"])-success
                alpha=success+self.prior_successes; beta=failure+self.prior_failures
                rate=alpha/(alpha+beta); deviation=math.sqrt(alpha*beta/((alpha+beta)**2*(alpha+beta+1)))
                c.execute("INSERT INTO base_rate_models VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(category,forecast_kind,horizon_bucket) DO UPDATE SET successes=excluded.successes,failures=excluded.failures,rate=excluded.rate,lower_bound=excluded.lower_bound,upper_bound=excluded.upper_bound,method=excluded.method,updated_at=excluded.updated_at",
                          (row["category"],row["forecast_kind"],row["horizon_bucket"],success,failure,rate,max(0,rate-1.64*deviation),min(1,rate+1.64*deviation),self.method,now)); updated+=1
        return updated
