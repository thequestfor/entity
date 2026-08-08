"""Extract safe, typed lookup targets from claim provenance."""

import json
import re
from urllib.parse import urlsplit

from agent.intelligence.store import utc_now


CVE_PATTERN = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE)
GHSA_PATTERN = re.compile(r"\bGHSA-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}\b", re.IGNORECASE)


class VerificationTargetPlanner:
    method = "typed-verification-target-v2"

    def __init__(self, store):
        self.store = store

    def ensure(self, connection, task):
        existing = connection.execute(
            "SELECT * FROM verification_targets WHERE task_id=?", (task["id"],)
        ).fetchone()
        if (existing and existing["target_status"] == "ready"
                and existing["method"] == self.method):
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
        groundings = connection.execute(
            "SELECT * FROM claim_groundings WHERE claim_id=? "
            "ORDER BY confidence DESC,id", (claim["id"],)
        ).fetchall()
        adapter = str(task["desired_source_kind"] or "independent-public")
        identifier_type, identifier_value, query, grounding_id = self._target(
            adapter, claim, evidence, groundings
        )
        expected = {
            "predicate": claim["predicate"],
            "value": claim["object"],
            "normalized_value": claim["normalized_object"],
            "topic": claim["topic"]
        }
        status = "ready" if query else "unresolvable"
        reason = "" if query else "No typed identifier or bounded lookup window is available"
        now = utc_now()
        if existing:
            connection.execute(
                """
                UPDATE verification_targets SET adapter=?,identifier_type=?,
                  identifier_value=?,query_parameters=?,expected_value=?,
                  target_status=?,method=?,grounding_id=?,schema_version='v2',
                  resolution_reason=?,refreshed_at=?,updated_at=? WHERE id=?
                """,
                (adapter, identifier_type, identifier_value,
                 self.store._json(query), self.store._json(expected), status,
                 self.method, grounding_id, reason, now, now, existing["id"])
            )
            target_id = existing["id"]
        else:
            cursor = connection.execute(
                """
                INSERT INTO verification_targets (
                  task_id,claim_id,adapter,identifier_type,identifier_value,
                  query_parameters,expected_value,target_status,method,
                  created_at,updated_at,grounding_id,schema_version,
                  resolution_reason,refreshed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (task["id"], claim["id"], adapter, identifier_type,
                 identifier_value, self.store._json(query),
                 self.store._json(expected), status, self.method, now, now,
                 grounding_id, "v2", reason, now)
            )
            target_id = cursor.lastrowid
        row = connection.execute(
            "SELECT * FROM verification_targets WHERE id=?", (target_id,)
        ).fetchone()
        return self._decode(row)

    def _target(self, adapter, claim, evidence, groundings=()):
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
        grounding_items = [dict(row) for row in groundings]
        if adapter == "usgs":
            official = next((item for item in documents
                             if item["source_id"] == "usgs_earthquakes"), None)
            if official:
                event_id = str(official["external_id"] or "").strip()
                if re.fullmatch(r"[A-Za-z0-9._-]{3,80}", event_id):
                    return "usgs_event_id", event_id, {"event_id": event_id}, None
            official_grounding = _authority_grounding(
                grounding_items, "usgs_earthquakes"
            )
            if official_grounding:
                event_id = official_grounding["value"]
                return "usgs_event_id", event_id, {"event_id": event_id}, official_grounding["id"]
            located = next((item for item in documents
                            if item.get("latitude") is not None
                            and item.get("longitude") is not None), None)
            if located:
                return "geo_time_window", "", {
                    "latitude": float(located["latitude"]),
                    "longitude": float(located["longitude"]),
                    "published_at": located.get("published_at"),
                    "radius_km": 100
                }, None
        if adapter == "nws-alerts":
            official = next((item for item in documents
                             if item["source_id"] == "nws_alerts"), None)
            if official:
                value = str(official["external_id"] or "")
                if value.startswith("http"):
                    value = urlsplit(value).path.rstrip("/").split("/")[-1]
                if re.fullmatch(r"[A-Za-z0-9._-]{3,200}", value):
                    return "nws_alert_id", value, {"alert_id": value}, None
        if adapter in {"cisa-kev", "github-advisories"}:
            cve = CVE_PATTERN.search(text)
            if cve:
                value = cve.group(0).upper()
                return "cve", value, {"cve": value}, None
            ghsa = GHSA_PATTERN.search(text)
            if ghsa and adapter == "github-advisories":
                value = ghsa.group(0).upper()
                return "ghsa", value, {"ghsa": value}, None
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
                    }, None
        if adapter == "fred":
            for item in documents:
                meta = item["metadata"]
                series = str(meta.get("series_id") or "").upper()
                date = str(meta.get("observation_date") or "")
                if re.fullmatch(r"[A-Z0-9._-]{1,80}", series):
                    return "fred_observation", f"{series}:{date}", {
                        "series_id": series, "date": date
                    }, None
        namespace = {
            "eonet": "nasa_eonet", "gdacs": "gdacs",
            "who-outbreaks": "who_outbreaks", "reliefweb": "reliefweb",
            "noaa-swpc": "noaa_space_weather_alerts"
        }.get(adapter)
        if namespace:
            grounding = _authority_grounding(grounding_items, namespace)
            if grounding:
                key = {
                    "eonet": "event_id", "gdacs": "event_id",
                    "who-outbreaks": "notice_id", "reliefweb": "report_id",
                    "noaa-swpc": "message_id"
                }[adapter]
                value = grounding["value"]
                return key, value, {key: value}, grounding["id"]
        if adapter == "firms":
            grounding = next((item for item in grounding_items
                              if item["grounding_type"] == "geo_time_window"), None)
            if grounding:
                try:
                    query = json.loads(grounding["value"])
                except (TypeError, ValueError):
                    query = {}
                if query:
                    query["radius_km"] = 25
                    return "geo_time_window", "", query, grounding["id"]
        return "", "", {}, None

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


def _authority_grounding(groundings, namespace):
    return next((item for item in groundings
                 if item.get("grounding_type") == "authority_record"
                 and item.get("namespace") == namespace), None)
