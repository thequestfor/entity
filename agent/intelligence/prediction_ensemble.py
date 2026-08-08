import math


def _logit(p):
    p=max(.01,min(.99,float(p))); return math.log(p/(1-p))


def _sigmoid(value): return 1/(1+math.exp(-value))


class PredictionEnsemble:
    method="fixed-log-odds-v1"
    weights={"base_rate":.5,"hypothesis":.3,"reasoning":.2}

    def combine(self,components):
        available={key:float(value) for key,value in components.items() if value is not None and key in self.weights}
        if not available: return .5,[]
        total=sum(self.weights[key] for key in available)
        pooled=sum((self.weights[key]/total)*_logit(value) for key,value in available.items())
        probability=max(.05,min(.95,_sigmoid(pooled)))
        return probability,[{"component":key,"probability":value,"weight":self.weights[key]/total} for key,value in available.items()]
