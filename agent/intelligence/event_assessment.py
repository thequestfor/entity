"""Deterministic epistemic assessments over canonical fused world events."""

import hashlib
import json
from dataclasses import dataclass

from agent.intelligence.store import utc_now


METHOD = "canonical-event-assessment-v1"
POLICY_VERSION = "truth-seeking-v1"


@dataclass(frozen=True)
class EventAssessmentResult:
    processed: int = 0
    changed: int = 0


class CanonicalEventAssessmentEngine:
    """Summarize epistemic state without converting reports into facts."""

    def __init__(self, store, enabled=True, batch_size=100):
        self.store = store
        self.enabled = bool(enabled)
        self.batch_size = max(1, min(500, int(batch_size)))

    def run_batch(self):
        if not self.enabled:
            return EventAssessmentResult()
        with self.store._connect() as connection:
            events = connection.execute(
                """SELECT events.* FROM world_events events
                   LEFT JOIN world_event_assessments assessments
                     ON assessments.world_event_id=events.id
                   WHERE events.status!='merged' AND (
                     assessments.world_event_id IS NULL OR
                     assessments.event_updated_at!=events.updated_at OR
                     EXISTS (
                       SELECT 1 FROM world_event_memberships memberships
                       JOIN world_event_observations observations
                         ON observations.id=memberships.observation_id
                       WHERE memberships.world_event_id=events.id
                         AND memberships.active=1
                         AND observations.captured_at>
                           assessments.evidence_cutoff_at
                     )
                   )
                   ORDER BY assessments.world_event_id IS NULL DESC,
                            events.last_seen_at DESC LIMIT ?""",
                (self.batch_size,),
            ).fetchall()
            changed = 0
            for event in events:
                assessment = self._assess(connection, dict(event))
                if assessment and self._store(connection, assessment):
                    changed += 1
        return EventAssessmentResult(len(events), changed)

    def _assess(self, connection, event):
        observations = connection.execute(
            """SELECT observations.*,documents.title document_title,
                      documents.url,documents.publisher_key,
                      documents.publisher_label,
                      COALESCE(NULLIF(documents.reporting_family_key,''),
                               NULLIF(documents.publisher_key,''),
                               documents.source_id) family_key,
                      sources.name source_name,sources.kind source_kind,
                      sources.credibility baseline_credibility,
                      policies.authority_class,policies.evidence_role,
                      COALESCE(assessment.effective_credibility,
                               reputation.learned_credibility,
                               sources.credibility) effective_credibility
               FROM world_event_memberships memberships
               JOIN world_event_observations observations
                 ON observations.id=memberships.observation_id
               JOIN documents ON documents.id=observations.document_id
               JOIN sources ON sources.id=observations.source_id
               LEFT JOIN source_policies policies ON policies.source_id=sources.id
               LEFT JOIN publisher_reputation reputation
                 ON reputation.publisher_key=documents.publisher_key
               LEFT JOIN publisher_assessments assessment
                 ON assessment.publisher_key=documents.publisher_key
                AND assessment.scope_kind='global' AND assessment.scope_value=''
               WHERE memberships.world_event_id=? AND memberships.active=1
                 AND observations.status='active'
               ORDER BY observations.captured_at,observations.id""",
            (event["id"],),
        ).fetchall()
        if not observations:
            return None
        reports = []
        families = set()
        direct = []
        document_ids = []
        observation_fingerprint = []
        for row in observations:
            item = dict(row)
            properties = self.store._json_load(item.get("properties"), {})
            title = str(properties.get("title") or item["document_title"] or "")
            family = str(item["family_key"] or item["source_id"])
            families.add(family)
            document_ids.append(item["document_id"])
            report = {
                "observation_id": item["id"], "document_id": item["document_id"],
                "title": title[:500], "publisher": item["publisher_label"],
                "publisher_key": item["publisher_key"], "source": item["source_name"],
                "family": family, "evidence_role": item["evidence_role"] or "report",
                "authority_class": item["authority_class"] or "unspecified",
                "credibility": round(float(item["effective_credibility"] or .5), 4),
                "captured_at": item["captured_at"], "url": item["url"],
            }
            reports.append(report)
            if (
                report["evidence_role"] in {"observation", "measurement"}
                and report["authority_class"] in {"official", "intergovernmental"}
            ):
                direct.append(report)
            observation_fingerprint.append((
                item["id"], item["payload_hash"], family, item["captured_at"]
            ))

        disputes = self._disputes(connection, document_ids)
        hypotheses = self._hypotheses(connection, event.get("situation_id"))
        family_count = len(families)
        facts = []
        for report in direct[:10]:
            facts.append({
                "kind": "direct-observation",
                "text": report["title"],
                "document_id": report["document_id"],
                "source": report["source"],
            })
        if family_count >= 2:
            facts.append({
                "kind": "independently-corroborated-report",
                "text": str(event["title"])[:500],
                "independent_family_count": family_count,
                "document_ids": sorted(set(document_ids))[:50],
            })
        if event.get("latitude") is not None and (direct or family_count >= 2):
            facts.append({
                "kind": "grounded-location", "latitude": event["latitude"],
                "longitude": event["longitude"],
                "country": event.get("country_name") or "",
            })

        unknowns = []
        if not direct and family_count < 2:
            unknowns.append("No direct observation or independent corroboration yet.")
        if event.get("latitude") is None:
            unknowns.append("Event location remains unresolved.")
        if not hypotheses:
            unknowns.append("Competing explanations have not yet been developed.")
        if disputes:
            status = "contested"
        elif direct:
            status = "directly-observed"
        elif family_count >= 2:
            status = "corroborated"
        else:
            status = "early-signal"
        confidence = float(event.get("confidence") or .5)
        if status == "early-signal":
            confidence = min(confidence, .49)
        elif direct:
            confidence = max(confidence, .7)
        elif family_count >= 2:
            confidence = max(confidence, min(.9, .6 + .05 * family_count))
        if disputes:
            confidence = max(.1, confidence - .15)
        cutoff = max(str(row["captured_at"]) for row in observations)
        raw = {
            "event_id": event["id"], "event_updated_at": event["updated_at"],
            "observations": observation_fingerprint,
            "disputes": disputes, "hypotheses": hypotheses,
            "policy": POLICY_VERSION,
        }
        input_hash = hashlib.sha256(json.dumps(
            raw, sort_keys=True, separators=(",", ":"), default=str
        ).encode()).hexdigest()
        return {
            "world_event_id": event["id"], "assessment_status": status,
            "headline": str(event["title"])[:500],
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
            "independent_family_count": family_count,
            "observation_count": len(observations),
            "direct_observation_count": len(direct),
            "established_facts": facts,
            "reported_claims": reports[-50:], "disputes": disputes,
            "hypotheses": hypotheses, "unknowns": unknowns,
            "evidence_document_ids": sorted(set(document_ids))[:200],
            "evidence_cutoff_at": cutoff, "event_updated_at": event["updated_at"],
            "input_hash": input_hash,
        }

    def _disputes(self, connection, document_ids):
        if not document_ids:
            return []
        placeholders = ",".join("?" for _ in document_ids)
        rows = connection.execute(
            f"""SELECT DISTINCT claims.id,claims.subject,claims.predicate,
                       claims.object,claims.truth_status,claims.confidence
                FROM claims JOIN claim_evidence evidence ON evidence.claim_id=claims.id
                JOIN document_versions versions
                  ON versions.id=evidence.document_version_id
                WHERE versions.document_id IN ({placeholders})
                  AND (claims.status='contested' OR
                       claims.truth_status IN ('refuted','contested'))
                ORDER BY claims.confidence DESC LIMIT 20""",
            document_ids,
        ).fetchall()
        return [dict(row) for row in rows]

    def _hypotheses(self, connection, situation_id):
        if not situation_id:
            return []
        rows = connection.execute(
            """SELECT id,title,description,probability,status,falsifiers
               FROM situation_hypotheses WHERE situation_id=? AND status='active'
               ORDER BY probability DESC LIMIT 10""", (situation_id,)
        ).fetchall()
        values = []
        for row in rows:
            item = dict(row)
            item["falsifiers"] = self.store._json_load(item["falsifiers"], [])
            values.append(item)
        return values

    def _store(self, connection, item):
        previous = connection.execute(
            "SELECT input_hash FROM world_event_assessments WHERE world_event_id=?",
            (item["world_event_id"],),
        ).fetchone()
        if previous and previous["input_hash"] == item["input_hash"]:
            return False
        now = utc_now()
        encoded = {
            key: self.store._json(item[key]) for key in (
                "established_facts", "reported_claims", "disputes", "hypotheses",
                "unknowns", "evidence_document_ids",
            )
        }
        connection.execute(
            """INSERT INTO world_event_assessments (
                 world_event_id,assessment_status,headline,confidence,
                 independent_family_count,observation_count,direct_observation_count,
                 established_facts,reported_claims,disputes,hypotheses,unknowns,
                 evidence_document_ids,evidence_cutoff_at,epistemic_policy_version,
                 method,input_hash,event_updated_at,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(world_event_id) DO UPDATE SET
                 assessment_status=excluded.assessment_status,
                 headline=excluded.headline,confidence=excluded.confidence,
                 independent_family_count=excluded.independent_family_count,
                 observation_count=excluded.observation_count,
                 direct_observation_count=excluded.direct_observation_count,
                 established_facts=excluded.established_facts,
                 reported_claims=excluded.reported_claims,
                 disputes=excluded.disputes,hypotheses=excluded.hypotheses,
                 unknowns=excluded.unknowns,
                 evidence_document_ids=excluded.evidence_document_ids,
                 evidence_cutoff_at=excluded.evidence_cutoff_at,
                 epistemic_policy_version=excluded.epistemic_policy_version,
                 method=excluded.method,input_hash=excluded.input_hash,
                 event_updated_at=excluded.event_updated_at,
                 updated_at=excluded.updated_at""",
            (
                item["world_event_id"], item["assessment_status"], item["headline"],
                item["confidence"], item["independent_family_count"],
                item["observation_count"], item["direct_observation_count"],
                encoded["established_facts"], encoded["reported_claims"],
                encoded["disputes"], encoded["hypotheses"], encoded["unknowns"],
                encoded["evidence_document_ids"], item["evidence_cutoff_at"],
                POLICY_VERSION, METHOD, item["input_hash"], item["event_updated_at"],
                now, now,
            ),
        )
        connection.execute(
            """INSERT OR IGNORE INTO world_event_assessment_history (
                 world_event_id,assessment_status,headline,confidence,
                 independent_family_count,observation_count,direct_observation_count,
                 established_facts,reported_claims,disputes,hypotheses,unknowns,
                 evidence_document_ids,evidence_cutoff_at,epistemic_policy_version,
                 method,input_hash,reason,created_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item["world_event_id"], item["assessment_status"], item["headline"],
                item["confidence"], item["independent_family_count"],
                item["observation_count"], item["direct_observation_count"],
                encoded["established_facts"], encoded["reported_claims"],
                encoded["disputes"], encoded["hypotheses"], encoded["unknowns"],
                encoded["evidence_document_ids"], item["evidence_cutoff_at"],
                POLICY_VERSION, METHOD, item["input_hash"],
                "Canonical event evidence or epistemic state changed.", now,
            ),
        )
        return True
