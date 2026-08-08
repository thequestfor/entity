"""Evidence-linked competing hypotheses with deterministic probability updates."""

import hashlib
import json
import math
from dataclasses import dataclass
from uuid import uuid4

from agent.intelligence.information_gaps import InformationGapPlanner
from agent.intelligence.store import utc_now


@dataclass(frozen=True)
class HypothesisResult:
    situations_processed: int = 0
    hypotheses_created: int = 0
    versions_created: int = 0
    gaps_created: int = 0


class HypothesisCompetitionEngine:
    method = "evidence-competition-v2"
    backfill_name = "hypothesis-competition-v2"

    def __init__(self, store, enabled=True, batch_size=20,
                 max_hypotheses=5, probability_floor=0.03):
        self.store = store
        self.enabled = bool(enabled)
        self.batch_size = max(1, min(100, int(batch_size)))
        self.max_hypotheses = max(3, min(8, int(max_hypotheses)))
        self.floor = max(.01, min(.1, float(probability_floor)))
        self.gaps = InformationGapPlanner(store)

    def run_batch(self):
        if not self.enabled:
            return HypothesisResult()
        now = utc_now()
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._state(connection, now)
            rows = connection.execute(
                "SELECT rowid situation_rowid,* FROM situations WHERE rowid>? "
                "ORDER BY rowid LIMIT ?",
                (state["cursor_rowid"], self.batch_size)
            ).fetchall()
            if not rows:
                connection.execute(
                    "UPDATE epistemic_backfill_state SET completed=1,"
                    "completed_at=?,updated_at=? WHERE name=?",
                    (now, now, self.backfill_name)
                )
                return HypothesisResult()
            created = versions = gaps = 0
            for situation in rows:
                c, v, g = self._process(connection, situation, now)
                created += c; versions += v; gaps += g
            connection.execute(
                "UPDATE epistemic_backfill_state SET cursor_rowid=?,"
                "processed=processed+?,updated=updated+?,completed=0,"
                "completed_at=NULL,updated_at=? WHERE name=?",
                (rows[-1]["situation_rowid"],len(rows),versions,now,
                 self.backfill_name)
            )
        return HypothesisResult(len(rows), created, versions, gaps)

    def _state(self, connection, now):
        row = connection.execute(
            "SELECT * FROM epistemic_backfill_state WHERE name=?",
            (self.backfill_name,)
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO epistemic_backfill_state "
                "(name,version,started_at,updated_at) VALUES (?,?,?,?)",
                (self.backfill_name,self.method,now,now)
            )
        elif row["version"] != self.method:
            connection.execute(
                "UPDATE epistemic_backfill_state SET version=?,cursor_rowid=0,"
                "processed=0,updated=0,completed=0,started_at=?,updated_at=?,"
                "completed_at=NULL WHERE name=?",
                (self.method,now,now,self.backfill_name)
            )
        return connection.execute(
            "SELECT * FROM epistemic_backfill_state WHERE name=?",
            (self.backfill_name,)
        ).fetchone()

    def _templates(self, situation):
        category = str(situation["category"] or "general").lower()
        base = [
            ("substantially-accurate", "The reported event is substantially accurate", .38),
            ("details-uncertain", "The event occurred but material details are uncertain", .30),
        ]
        if any(token in category for token in ("cyber", "vulnerability")):
            alternatives = [
                ("exploitation-unconfirmed", "The weakness may be real while active exploitation remains unconfirmed", .14),
                ("scope-uncertain", "The affected products or organizations may be narrower than reported", .10),
                ("attribution-unsupported", "The incident may be real while actor attribution is unsupported", .08),
            ]
        elif any(token in category for token in ("conflict", "military", "security")):
            alternatives = [
                ("attribution-unsupported", "The event may be real while the claimed actor or attribution is unsupported", .14),
                ("recycled-or-outdated", "Material evidence may be recycled, stale, or superseded", .10),
                ("localized-not-general", "A localized event may be overstated as a broader development", .08),
            ]
        elif any(token in category for token in ("weather", "earthquake", "wildfire", "disaster")):
            alternatives = [
                ("measurement-revised", "The event is real but preliminary measurements may be revised", .14),
                ("secondary-impact-uncertain", "The event is real while reported downstream impacts remain uncertain", .10),
                ("outdated", "The alert or measurement may have been superseded", .08),
            ]
        elif any(token in category for token in ("health", "outbreak", "disease")):
            alternatives = [
                ("scale-uncertain", "The event may be real while its reported scale remains uncertain", .14),
                ("cause-unsupported", "The observed event may be real while its proposed cause is unsupported", .10),
                ("reporting-lag", "Reporting delay may make the apparent trend misleading", .08),
            ]
        elif any(token in category for token in ("economic", "finance", "market")):
            alternatives = [
                ("provisional-revision", "The reported measurement may be provisional and later revised", .14),
                ("cause-unsupported", "The measurement may be real while its proposed explanation is unsupported", .10),
                ("aggregation-distortion", "Aggregation or geographic scope may distort the reported conclusion", .08),
            ]
        else:
            alternatives = [
                ("distinct-events", "Reports combine incompatible or distinct events", .14),
                ("outdated", "Material reporting is outdated or superseded", .10),
                ("cause-unsupported", "The event may be real while its proposed cause or attribution is unsupported", .08),
            ]
        return (base + alternatives)[:self.max_hypotheses]

    def _process(self, connection, situation, now):
        claims = connection.execute(
            "SELECT * FROM claims WHERE situation_id=? AND status!='superseded'",
            (situation["id"],)
        ).fetchall()
        if not claims:
            return 0, 0, 0
        connection.execute(
            "UPDATE situation_hypotheses SET status='retired',retired_at=?,"
            "updated_at=? WHERE situation_id=? AND status='active' "
            "AND method LIKE 'evidence-competition-v%' AND method!=?",
            (now, now, situation["id"], self.method)
        )
        snapshot = [{"id":c["id"],"truth":c["truth_status"],
                     "confidence":c["resolution_confidence"]} for c in claims]
        digest = hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest()
        seen = connection.execute(
            "SELECT 1 FROM hypothesis_generation_runs WHERE situation_id=? "
            "AND input_snapshot_hash=? AND method=?",
            (situation["id"],digest,self.method)
        ).fetchone()
        if seen:
            return 0, 0, 0
        created = 0
        hypotheses = []
        for key,title,prior in self._templates(situation):
            row = connection.execute(
                "SELECT * FROM situation_hypotheses WHERE situation_id=? "
                "AND hypothesis_key=? AND method=?",
                (situation["id"],key,self.method)
            ).fetchone()
            if row is None:
                hypothesis_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO situation_hypotheses (
                      id,situation_id,title,description,probability,status,
                      supporting_claim_ids,contradicting_claim_ids,falsifiers,
                      method,created_at,updated_at,hypothesis_key,hypothesis_type,
                      prior_probability,assumptions,open_questions,
                      evidence_cutoff_at,generator_version
                    ) VALUES (?,?,?,?,?,'active','[]','[]',?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (hypothesis_id,situation["id"],title,
                     "Evidence-linked deterministic competing explanation.",prior,
                     self.store._json(self._falsifiers(key)),self.method,now,now,
                     key,"alternative",prior,"[]","[]",now,self.method)
                )
                created += 1
                row = connection.execute(
                    "SELECT * FROM situation_hypotheses WHERE id=?",
                    (hypothesis_id,)
                ).fetchone()
            hypotheses.append(row)
        scores=[]; links={}
        for hypothesis in hypotheses:
            log_score=math.log(max(self.floor,float(hypothesis["prior_probability"])))
            support=[]; oppose=[]
            for claim in claims:
                relation,lr=self._claim_effect(hypothesis["hypothesis_key"],claim)
                if relation is None: continue
                log_score += math.log(max(.125,min(8.0,lr)))
                (support if relation=="supports" else oppose).append(claim["id"])
                connection.execute(
                    "INSERT OR REPLACE INTO hypothesis_claim_links VALUES (?,?,?,?,?,?,?,?)",
                    (hypothesis["id"],claim["id"],relation,lr,"",self.method,now,now)
                )
            scores.append(log_score); links[hypothesis["id"]]=(support,oppose)
        maximum=max(scores); raw=[math.exp(score-maximum) for score in scores]
        total=sum(raw); probabilities=[max(self.floor,value/total) for value in raw]
        norm=sum(probabilities); probabilities=[value/norm for value in probabilities]
        version_count=0
        for hypothesis,probability in zip(hypotheses,probabilities):
            support,oppose=links[hypothesis["id"]]
            connection.execute(
                "UPDATE situation_hypotheses SET probability=?,"
                "supporting_claim_ids=?,contradicting_claim_ids=?,"
                "evidence_cutoff_at=?,updated_at=? WHERE id=?",
                (round(probability,4),self.store._json(support),
                 self.store._json(oppose),now,now,hypothesis["id"])
            )
            version=connection.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM hypothesis_versions "
                "WHERE hypothesis_id=?",(hypothesis["id"],)
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO hypothesis_versions VALUES (NULL,?,?,?,?,?,?,?,?,?,?)",
                (hypothesis["id"],version,hypothesis["prior_probability"],
                 round(probability,4),self.store._json(support),
                 self.store._json(oppose),digest,
                 "Independent claim likelihood update.",self.method,now)
            )
            version_count += 1
        ranked=sorted([dict(h) for h in hypotheses],
                      key=lambda h: float(h["probability"]),reverse=True)
        gaps=self.gaps.plan(connection,situation,ranked,claims)
        connection.execute(
            "INSERT INTO hypothesis_generation_runs VALUES (NULL,?,?,?,?,?,?,?)",
            (situation["id"],digest,created,"success","",self.method,now)
        )
        return created,version_count,gaps

    def _claim_effect(self,key,claim):
        truth=claim["truth_status"]
        ctype=claim["claim_type"]
        confidence=max(.2,float(claim["resolution_confidence"] or .2))
        if key=="substantially-accurate":
            if truth=="corroborated": return "supports",1+5*confidence
            if truth=="refuted": return "contradicts",1/(1+5*confidence)
        if key=="details-uncertain" and truth in {"unverified","disputed","indeterminate"}:
            return "supports",1.8
        if key=="distinct-events" and claim["status"]=="contested":
            return "supports",3.0
        if key=="outdated" and claim["status"]=="superseded":
            return "supports",3.0
        if key=="cause-unsupported" and ctype in {"causal_claim","interpretation"}:
            return "supports",2.0 if truth!="corroborated" else .5
        if key=="attribution-unsupported" and ctype in {"attributed_assertion","causal_claim","interpretation"}:
            return "supports",2.0 if truth!="corroborated" else .5
        if key in {"scope-uncertain","scale-uncertain","secondary-impact-uncertain","localized-not-general","aggregation-distortion"} and truth in {"unverified","disputed","indeterminate"}:
            return "supports",1.7
        if key in {"measurement-revised","provisional-revision"} and claim["predicate"] in {"seismic.magnitude","event.alert_level","event.status"}:
            return "supports",1.8 if truth!="corroborated" else .7
        if key=="exploitation-unconfirmed" and truth!="corroborated":
            return "supports",1.8
        if key=="reporting-lag" and truth in {"unverified","indeterminate"}:
            return "supports",1.5
        if key=="recycled-or-outdated" and claim["status"] in {"contested","superseded"}:
            return "supports",2.5
        return None,1.0

    def _falsifiers(self,key):
        return {
            "substantially-accurate":["Primary evidence refutes a core factual claim."],
            "details-uncertain":["Independent primary evidence resolves disputed details."],
            "distinct-events":["A shared identifier and consistent time/location reconcile reports."],
            "outdated":["Current primary evidence confirms the original detail remains valid."],
            "cause-unsupported":["Direct primary evidence establishes the proposed cause or attribution."]
            ,"attribution-unsupported":["Primary evidence identifies the actor with a documented chain of attribution."]
            ,"recycled-or-outdated":["Provenance verifies the evidence is current and belongs to this event."]
            ,"localized-not-general":["Independent measurements establish the reported broader geographic scope."]
            ,"exploitation-unconfirmed":["A primary incident record confirms exploitation in the wild."]
            ,"scope-uncertain":["A complete affected-product or victim inventory confirms the reported scope."]
            ,"measurement-revised":["A reviewed measurement confirms the preliminary value without material revision."]
            ,"secondary-impact-uncertain":["Primary impact assessments confirm the downstream effects."]
            ,"scale-uncertain":["A primary case count or denominator confirms the reported scale."]
            ,"reporting-lag":["Event-date data show the apparent trend persists after reporting-delay adjustment."]
            ,"provisional-revision":["A final release confirms the provisional measurement."]
            ,"aggregation-distortion":["Disaggregated data support the same conclusion across relevant regions."]
        }.get(key,[])
