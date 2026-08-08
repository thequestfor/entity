from uuid import uuid4

from agent.intelligence.store import utc_now
from agent.intelligence.verification import SOURCE_KIND_BY_TOPIC


class InformationGapPlanner:
    method = "information-gap-v1"

    def __init__(self, store, max_per_situation=3):
        self.store = store
        self.max_per_situation = max(1, min(5, int(max_per_situation)))

    def plan(self, connection, situation, hypotheses, claims):
        if len(hypotheses) < 2:
            return 0
        uncertain = [
            claim for claim in claims
            if claim["truth_status"] in {"unverified", "disputed", "indeterminate"}
            and claim["verifiability"] == "checkable"
        ]
        created = 0
        now = utc_now()
        topic = str(situation["category"] or "general")
        for claim in uncertain[:self.max_per_situation]:
            question = (
                f"What independent primary evidence resolves whether "
                f"{claim['predicate']} is {claim['object']}?"
            )
            key = f"{situation['id']}:{claim['predicate']}:{claim['normalized_object']}"
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO intelligence_gaps (
                  id,situation_id,hypothesis_id,question,target_predicate,
                  desired_source_kind,expected_information_value,priority,
                  dedupe_key,method,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (str(uuid4()), situation["id"], hypotheses[0]["id"], question,
                 claim["predicate"], SOURCE_KIND_BY_TOPIC.get(topic,"independent-public"),
                 0.75, min(1.0, 0.5+float(claim["core_importance"] or .5)*.4),
                 key, self.method, now, now)
            )
            created += int(cursor.rowcount > 0)
        return created
