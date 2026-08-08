"""Blinded deterministic safety and symmetry gates for intelligence learning."""

import argparse
import json
from dataclasses import dataclass

from dotenv import load_dotenv

from agent.intelligence.claim_extraction import HybridClaimExtractor
from agent.intelligence.config import IntelligenceConfig
from agent.intelligence.prediction_ensemble import PredictionEnsemble
from agent.intelligence.store import IntelligenceStore, utc_now
from agent.intelligence.verification import VerificationEngine
from agent.intelligence.authoritative_verification import compare_observation
from agent.intelligence.ensemble_training import EnsembleTrainer, FEATURES


SUITE_VERSION="blinded-intelligence-v4"


@dataclass(frozen=True)
class EvaluationCase:
    key: str
    category: str
    passed: bool
    critical: bool = False
    difference: float = 0.0
    details: dict = None


def anonymize_evidence(items):
    aliases={}
    result=[]
    for item in items:
        family=str(item.get("independence_key") or item.get("publisher") or "unknown")
        aliases.setdefault(family,f"source_{len(aliases)+1}")
        result.append({
            **{key:value for key,value in item.items()
               if key not in {"publisher","source_name","source_id"}},
            "publisher":aliases[family]
        })
    return result


class IntelligenceEvaluationEngine:
    def __init__(self,store): self.store=store

    def run(self):
        started=utc_now(); cases=self._cases(); finished=utc_now()
        passed=sum(case.passed for case in cases); failed=len(cases)-passed
        critical=sum(case.critical and not case.passed for case in cases)
        with self.store._connect() as c:
            run=c.execute("INSERT INTO intelligence_evaluation_runs (suite_version,outcome,passed,failed,critical_failures,metrics,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?)",
                          (SUITE_VERSION,"passed" if not failed else "failed",passed,failed,critical,self.store._json({"deterministic_symmetry_threshold":.03}),started,finished))
            run_id=run.lastrowid
            for case in cases:
                c.execute("INSERT INTO intelligence_evaluation_cases (run_id,case_key,category,passed,critical,difference,details,created_at) VALUES (?,?,?,?,?,?,?,?)",
                          (run_id,case.key,case.category,int(case.passed),int(case.critical),case.difference,self.store._json(case.details or {}),finished))
            self._update_gates(c,run_id,critical,failed,finished)
        return {"run_id":run_id,"passed":passed,"failed":failed,"critical_failures":critical}

    def _cases(self):
        ensemble=PredictionEnsemble()
        left,_=ensemble.combine({"base_rate":.4,"hypothesis":.7,"reasoning":.55})
        right,_=ensemble.combine({"reasoning":.55,"hypothesis":.7,"base_rate":.4})
        quote=HybridClaimExtractor().extract({"title":"Briefing","summary":"Minister Rao said that the bridge was destroyed.","category":"conflict","metadata":{}})
        quoted=[c for c in quote if "destroyed" in c.value]
        private_count=0
        with self.store._connect() as c:
            private_count=c.execute("""
              SELECT COUNT(*) FROM claims JOIN claim_evidence e ON e.claim_id=claims.id
              JOIN document_versions v ON v.id=e.document_version_id
              JOIN documents d ON d.id=v.document_id JOIN sources s ON s.id=d.source_id
              WHERE s.kind='private_mail'
            """).fetchone()[0]
        masked=anonymize_evidence([
            {"publisher":"Famous A","independence_key":"a","weight":.8},
            {"publisher":"Unknown B","independence_key":"b","weight":.8}
        ])
        swapped=anonymize_evidence([
            {"publisher":"Unknown B","independence_key":"a","weight":.8},
            {"publisher":"Famous A","independence_key":"b","weight":.8}
        ])
        verifier=VerificationEngine(self.store)
        duplicate_family=verifier._signal([
            {"source_id":"untrusted-a","family_key":"wire-copy",
             "credibility":.99,"document_version_id":1},
            {"source_id":"untrusted-b","family_key":"wire-copy",
             "credibility":.99,"document_version_id":2}
        ],"independent-public")
        forged_authority=verifier._signal([
            {"source_id":"usgs-lookalike","family_key":"impostor",
             "credibility":1.0,"document_version_id":3}
        ],"usgs")
        inverse,_=ensemble.combine({
            "base_rate":.6,"hypothesis":.3,"reasoning":.45
        })
        missing_outcome,_,_,_=compare_observation(
            {"predicate":"event.reported","value":"true"},
            {"found":False},closed_world=True
        )
        revision_outcome,_,_,_=compare_observation(
            {"predicate":"seismic.magnitude","value":"4.8",
             "normalized_value":"4.8"},
            {"found":True,"magnitude":4.9},closed_world=True
        )
        closed_absence,_,_,_=compare_observation(
            {"predicate":"cyber.known_exploited","value":"true"},
            {"found":False},closed_world=True
        )
        synthetic=[
            {"situation_id":f"s-{index//2}","created_at":f"{index:04d}"}
            for index in range(80)
        ]
        trainer=EnsembleTrainer(
            self.store,minimum_samples=50,minimum_validation=20
        )
        train,validation=trainer._out_of_time_split(synthetic)
        train_situations={item["situation_id"] for item in train}
        validation_situations={item["situation_id"] for item in validation}
        with self.store._connect() as c:
            future_evidence=c.execute("""
              SELECT COUNT(*) FROM forecast_evidence evidence
              JOIN forecasts ON forecasts.id=evidence.forecast_id
              WHERE forecasts.evidence_cutoff_at IS NOT NULL
                AND evidence.observed_at>forecasts.evidence_cutoff_at
            """).fetchone()[0]
            invented_authority=c.execute(
                "SELECT COUNT(*) FROM claim_groundings WHERE "
                "method='schema_model_grounding' AND "
                "grounding_type='authority_record'"
            ).fetchone()[0]
            self_verified=c.execute("""
              SELECT COUNT(*) FROM publisher_claim_outcomes outcomes
              JOIN claim_evidence evidence ON evidence.claim_id=outcomes.claim_id
              JOIN document_versions versions
                ON versions.id=evidence.document_version_id
              JOIN documents ON documents.id=versions.document_id
              WHERE outcomes.verifier_source_id!=''
                AND outcomes.verifier_source_id=documents.source_id
            """).fetchone()[0]
        return [
            EvaluationCase("component-order-symmetry","symmetry",abs(left-right)<=.03,True,abs(left-right)),
            EvaluationCase("publisher-label-blinding","bias",masked==swapped,True,0,{"masked":masked}),
            EvaluationCase("quoted-proposition-not-endorsed","attribution",all(c.claim_type!="direct_fact" for c in quoted),True),
            EvaluationCase("private-mail-exclusion","privacy",private_count==0,True,float(private_count)),
            EvaluationCase("probability-bounds","calibration",.05<=left<=.95,False),
            EvaluationCase("duplicate-family-not-independent","independence",duplicate_family is None,True),
            EvaluationCase("authority-id-is-allowlisted","provenance",forged_authority is None,True),
            EvaluationCase("directional-complement-symmetry","symmetry",abs((left+inverse)-1)<=.03,True,abs((left+inverse)-1)),
            EvaluationCase("absence-is-not-generic-refutation","truth-maintenance",missing_outcome=="inconclusive",True),
            EvaluationCase("authoritative-revision-is-not-refutation","truth-maintenance",revision_outcome=="revises",True),
            EvaluationCase("closed-catalog-absence-can-refute","truth-maintenance",closed_absence=="refutes",True),
            EvaluationCase("forecast-evidence-cutoff","leakage",future_evidence==0,True,float(future_evidence)),
            EvaluationCase("situation-grouped-time-split","leakage",not (train_situations & validation_situations),True),
            EvaluationCase("model-cannot-invent-authority-ids","grounding",invented_authority==0,True,float(invented_authority)),
            EvaluationCase("authority-does-not-self-award","reliability",self_verified==0,True,float(self_verified)),
            EvaluationCase("source-identity-not-training-feature","bias",all("source" not in name and "publisher" not in name for name in FEATURES),True),
            EvaluationCase("framing-not-factual-component","bias","framing_signal" not in FEATURES,True),
            EvaluationCase("portfolio-probability-bounds","calibration",.05<=inverse<=.95,False)
        ]

    def _update_gates(self,c,run_id,critical,failed,now):
        calibration=self.store.forecast_calibration()
        resolved=int(calibration.get("v2_resolved") or 0)
        brier=calibration.get("v2_brier_score")
        mature_cell=c.execute(
            "SELECT COALESCE(MAX(evaluated_count),0) FROM publisher_reliability_cells"
        ).fetchone()[0]
        reliability_ready=(not critical and int(mature_cell or 0)>=12)
        c.execute("UPDATE intelligence_feature_gates SET status=?,reason=?,evaluation_run_id=?,sample_count=?,updated_at=? WHERE feature='topic_reliability'",
                  ("active" if reliability_ready else "shadow",
                   "Scoped outcome and symmetry gates passed" if reliability_ready else "Awaiting 12 resolved outcomes in a topic/type cell",
                   run_id,int(mature_cell or 0),now))
        hypothesis_status="active" if not critical else "blocked"
        c.execute("UPDATE intelligence_feature_gates SET status=?,reason=?,evaluation_run_id=?,sample_count=?,updated_at=? WHERE feature='hypothesis_competition'",
                  (hypothesis_status,"Blinded deterministic suite passed" if not critical else "Critical evaluation failure",run_id,resolved,now))
        forecast_ready=(not critical and resolved>=50 and brier is not None and float(brier)<=.23 and float(calibration.get("v2_resolution_coverage") or 0)>=.7)
        c.execute("UPDATE intelligence_feature_gates SET status=?,reason=?,evaluation_run_id=?,sample_count=?,metric=?,required_metric=.23,updated_at=? WHERE feature='forecast_v2'",
                  ("active" if forecast_ready else "shadow","Promotion criteria met" if forecast_ready else "Awaiting 50 resolved forecasts, coverage, and Brier gate",run_id,resolved,brier,now))
        shadow_model=c.execute(
            "SELECT id FROM forecast_model_versions WHERE status='shadow' "
            "ORDER BY promoted_at DESC LIMIT 1"
        ).fetchone()
        learned_status="shadow" if shadow_model and not critical else "blocked"
        learned_reason=(
            "Validated candidate is available in shadow mode"
            if learned_status=="shadow" else
            "Awaiting 100 training forecasts, 30 out-of-time validation forecasts, and safe improvement"
        )
        c.execute(
            "UPDATE intelligence_feature_gates SET status=?,reason=?,"
            "evaluation_run_id=?,sample_count=?,updated_at=? "
            "WHERE feature='learned_ensemble'",
            (learned_status,learned_reason,run_id,resolved,now)
        )


def main():
    parser=argparse.ArgumentParser(); parser.parse_args(); load_dotenv('.env')
    store=IntelligenceStore(IntelligenceConfig.from_env().database_path)
    print(json.dumps(IntelligenceEvaluationEngine(store).run(),indent=2))


if __name__=='__main__': main()
