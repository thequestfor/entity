import hashlib
import json

from agent.intelligence.store import utc_now


class TemporalFeatureExtractor:
    version="situation-temporal-v1"

    def __init__(self,store): self.store=store

    def snapshot(self,situation_id):
        with self.store._connect() as c:
            row=c.execute("""
              SELECT COUNT(DISTINCT d.id) documents,
                COUNT(DISTINCT COALESCE(NULLIF(d.reporting_family_key,''),d.publisher_key,d.source_id)) families,
                SUM(cl.truth_status='corroborated') corroborated,
                SUM(cl.truth_status IN ('disputed','refuted')) disputed,
                SUM(cl.evidence_role='primary') primary_claims
              FROM situations s LEFT JOIN situation_documents sd ON sd.situation_id=s.id
              LEFT JOIN documents d ON d.id=sd.document_id
              LEFT JOIN claims cl ON cl.situation_id=s.id WHERE s.id=? GROUP BY s.id
            """,(situation_id,)).fetchone()
        features=dict(row) if row else {"documents":0,"families":0,"corroborated":0,"disputed":0,"primary_claims":0}
        digest=hashlib.sha256(json.dumps(features,sort_keys=True).encode()).hexdigest()
        with self.store._connect() as c:
            c.execute("INSERT OR IGNORE INTO situation_feature_snapshots (situation_id,feature_version,features,snapshot_hash,observed_at) VALUES (?,?,?,?,?)",
                      (situation_id,self.version,self.store._json(features),digest,utc_now()))
        return features,digest
