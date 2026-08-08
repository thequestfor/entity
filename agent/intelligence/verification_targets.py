"""Extract safe, typed lookup targets from claim provenance."""

import json
import re
from urllib.parse import urlsplit

from agent.intelligence.store import utc_now


CVE_PATTERN = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE)
GHSA_PATTERN = re.compile(r"\bGHSA-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}\b", re.IGNORECASE)


class VerificationTargetPlanner:
    method = "typed-verification-target-v1"

    def __init__(self, store):
        self.store = store

    def ensure(self, connection, task):
        existing = connection.execute(
            "SELECT * FROM verification_targets WHERE task_id=?", (task["id"],)
        ).fetchone()
        if existing:
            return self._decode(existing)
        claim = connection.execute(
            "SELECT * FROM claims WHERE id=?", (task["claim_id"],)
        ).fetchone()
        if not claim:
            return None
        evidence = connection.execute(
            """
            SELECT documents.*,sources.kind AS source_kind
            FROM claim_evidence evidence
            JOIN document_versions versions
              ON versions.id=evidence.document_version_id
            JOIN documents ON documents.id=versions.document_id
            JOIN sources ON sources.id=documents.source_id
            WHERE evidence.claim_id=?
            ORDER BY documents.retrieved_at DESC
            """, (claim["id"],)
        ).fetchall()
        adapter = str(task["desired_source_kind"] or "independent-public")
        identifier_type, identifier_value, query = self._target(
            adapter, claim, evidence
        )
        expected = {
            "predicate": claim["predicate"],
            "value": claim["object"],
            "normalized_value": claim["normalized_object"],
            "topic": claim["topic"]
        }
        status = "ready" if query else "unresolvable"
        now = utc_now()
        cursor = connection.execute(
            """
            INSERT INTO verification_targets (
              task_id,claim_id,adapter,identifier_type,identifier_value,
              query_parameters,expected_value,target_status,method,
              created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (task["id"], claim["id"], adapter, identifier_type,
             identifier_value, self.store._json(query),
             self.store._json(expected), status, self.method, now, now)
        )
        row = connection.execute(
            "SELECT * FROM verification_targets WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
        return self._decode(row)

    def _target(self, adapter, claim, evidence):
        documents = []
        for row in evidence:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.get("metadata") or "{}")
            except (TypeError, ValueError):
                item["metadata"] = {}
            documents.append(item)
        text = " ".join(
            [str(claim["object"]), str(claim["normalized_object"])]
            + [f"{item['title']} {item['summary']}" for item in documents]
        )
        if adapter == "usgs":
            official = next((item for item in documents
                             if item["source_id"] == "usgs_earthquakes"), None)
            if official:
                event_id = str(official["external_id"] or "").strip()
                if re.fullmatch(r"[A-Za-z0-9._-]{3,80}", event_id):
                    return "usgs_event_id", event_id, {"event_id": event_id}
            located = next((item for item in documents
                            if item.get("latitude") is not None
                            and item.get("longitude") is not None), None)
            if located:
                return "geo_time_window", "", {
                    "latitude": float(located["latitude"]),
                    "longitude": float(located["longitude"]),
                    "published_at": located.get("published_at"),
                    "radius_km": 100
                }
        if adapter == "nws-alerts":
            official = next((item for item in documents
                             if item["source_id"] == "nws_alerts"), None)
            if official:
                value = str(official["external_id"] or "")
                if value.startswith("http"):
                    value = urlsplit(value).path.rstrip("/").split("/")[-1]
                if re.fullmatch(r"[A-Za-z0-9._-]{3,200}", value):
                    return "nws_alert_id", value, {"alert_id": value}
        if adapter in {"cisa-kev", "github-advisories"}:
            cve = CVE_PATTERN.search(text)
            if cve:
                value = cve.group(0).upper()
                return "cve", value, {"cve": value}
            ghsa = GHSA_PATTERN.search(text)
            if ghsa and adapter == "github-advisories":
                value = ghsa.group(0).upper()
                return "ghsa", value, {"ghsa": value}
        if adapter == "world-bank":
            for item in documents:
                meta = item["metadata"]
                country = str(meta.get("country_code") or "").upper()
                indicator = str(meta.get("indicator_code") or "").upper()
                year = str(meta.get("year") or "")
                if country and indicator and re.fullmatch(r"\d{4}", year):
                    value = f"{country}:{indicator}:{year}"
                    return "world_bank_observation", value, {
                        "country": country, "indicator": indicator, "year": year
                    }
        if adapter == "fred":
            for item in documents:
                meta = item["metadata"]
                series = str(meta.get("series_id") or "").upper()
                date = str(meta.get("observation_date") or "")
                if re.fullmatch(r"[A-Z0-9._-]{1,80}", series):
                    return "fred_observation", f"{series}:{date}", {
                        "series_id": series, "date": date
                    }
        return "", "", {}

    def _decode(self, row):
        if not row:
            return None
        item = dict(row)
        for key in ("query_parameters", "expected_value"):
            try:
                item[key] = json.loads(item[key] or "{}")
            except (TypeError, ValueError):
                item[key] = {}
        return item
