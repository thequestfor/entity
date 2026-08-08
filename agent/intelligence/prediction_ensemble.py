import json
import math


def _logit(p):
    p=max(.01,min(.99,float(p))); return math.log(p/(1-p))


def _sigmoid(value): return 1/(1+math.exp(-value))


class PredictionEnsemble:
    method="fixed-log-odds-v1"
    weights={"base_rate":.5,"hypothesis":.3,"reasoning":.2}

    def __init__(self, store=None, mode="fixed"):
        self.store = store
        self.mode = mode if mode in {"fixed", "shadow", "active"} else "fixed"
        self.last_method = self.method

    def combine(self,components,features=None):
        available={key:float(value) for key,value in components.items() if value is not None and key in self.weights}
        if not available: return .5,[]
        learned = self._learned_probability(available, features or {})
        if learned is not None:
            probability, coefficients, method = learned
            self.last_method = method
            total=sum(max(0,coefficients[index]) for index in range(1,4)) or 1
            return probability,[
                {"component":key,"probability":available[key],
                 "weight":max(0,coefficients[index])/total}
                for index,key in enumerate(
                    ("base_rate","hypothesis","reasoning"), start=1
                ) if key in available
            ]
        total=sum(self.weights[key] for key in available)
        pooled=sum((self.weights[key]/total)*_logit(value) for key,value in available.items())
        probability=max(.05,min(.95,_sigmoid(pooled)))
        self.last_method = self.method
        return probability,[{"component":key,"probability":value,"weight":self.weights[key]/total} for key,value in available.items()]

    def _learned_probability(self, components, features):
        if self.store is None or self.mode == "fixed":
            return None
        wanted = "active" if self.mode == "active" else "shadow"
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM forecast_model_versions WHERE status=? "
                "ORDER BY promoted_at DESC,created_at DESC LIMIT 1", (wanted,)
            ).fetchone()
        if not row:
            return None
        try:
            artifact=json.loads(row["coefficients"] or "{}")
            coefficients=[float(value) for value in artifact["coefficients"]]
        except (KeyError,TypeError,ValueError,json.JSONDecodeError):
            return None
        claims=max(1,int(features.get("corroborated",0))
                   +int(features.get("disputed",0)))
        vector=[1.0,_logit(components.get("base_rate",.5)),
                _logit(components.get("hypothesis",.5)),
                _logit(components.get("reasoning",.5)),
                math.log1p(max(0,int(features.get("family_count",0)))),
                int(features.get("corroborated",0))/claims,
                int(features.get("disputed",0))/claims]
        if len(coefficients)!=len(vector):
            return None
        probability=max(.05,min(.95,_sigmoid(sum(
            coefficient*value for coefficient,value in zip(coefficients,vector)
        ))))
        return probability,coefficients,str(row["method"])
