"""Typed read-only lookups against fixed authoritative API endpoints."""

import hashlib
import json
import math
import re
import urllib.parse
from datetime import UTC, datetime, timedelta


SOURCE_BY_ADAPTER = {
    "usgs": "usgs_earthquakes",
    "nws-alerts": "nws_alerts",
    "cisa-kev": "cisa_known_exploited_vulnerabilities",
    "github-advisories": "github_security_advisories",
    "world-bank": "world_bank_indicators",
    "fred": "fred_economic_indicators"
}


class AuthoritativeVerificationRegistry:
    """Execute only parameterized requests for known connector hosts."""

    def __init__(self, connectors=()):
        self.connectors = {
            item.source_id: item for item in connectors
            if getattr(item, "enabled", False)
        }

    def available(self, adapter):
        return SOURCE_BY_ADAPTER.get(adapter) in self.connectors

    def safe_error(self, error):
        message = str(error)
        for connector in self.connectors.values():
            secret = str(getattr(connector, "api_key", "") or "")
            if secret:
                message = message.replace(secret, "[REDACTED]")
        return message[:500]

    def query(self, target):
        adapter = target["adapter"]
        source_id = SOURCE_BY_ADAPTER.get(adapter)
        connector = self.connectors.get(source_id)
        if not connector or target["target_status"] != "ready":
            return None
        query = target["query_parameters"]
        if adapter == "usgs":
            snapshot, observed, closed = self._usgs(connector, query)
        elif adapter == "nws-alerts":
            snapshot, observed, closed = self._nws(connector, query)
        elif adapter == "cisa-kev":
            snapshot, observed, closed = self._cisa(connector, query)
        elif adapter == "github-advisories":
            snapshot, observed, closed = self._github(connector, query)
        elif adapter == "world-bank":
            snapshot, observed, closed = self._world_bank(connector, query)
        elif adapter == "fred":
            snapshot, observed, closed = self._fred(connector, query)
        else:
            return None
        outcome, revision, confidence, reason = compare_observation(
            target["expected_value"], observed, closed
        )
        safe_snapshot = _bounded_snapshot(snapshot)
        digest = hashlib.sha256(
            json.dumps(safe_snapshot, sort_keys=True, default=str).encode()
        ).hexdigest()
        return {
            "source_id": source_id, "outcome": outcome,
            "observed_value": observed, "confidence": confidence,
            "basis": "authoritative-query", "revision_kind": revision,
            "closed_world": closed, "response_hash": digest,
            "response_snapshot": safe_snapshot, "reason": reason
        }

    def _usgs(self, connector, query):
        event_id = str(query.get("event_id") or "")
        if event_id:
            if not re.fullmatch(r"[A-Za-z0-9._-]{3,80}", event_id):
                raise ValueError("Invalid USGS event identifier")
            url = (
                "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/"
                + urllib.parse.quote(event_id, safe="") + ".geojson"
            )
            payload = connector.fetch_json(url)
            feature = payload
        else:
            latitude = _bounded_float(query.get("latitude"), -90, 90)
            longitude = _bounded_float(query.get("longitude"), -180, 180)
            radius = _bounded_float(query.get("radius_km", 100), 1, 500)
            published = _parse_time(query.get("published_at"))
            if published is None:
                raise ValueError("USGS geospatial lookup requires an event time")
            parameters = urllib.parse.urlencode({
                "format": "geojson",
                "starttime": (published-timedelta(hours=2)).isoformat(),
                "endtime": (published+timedelta(hours=2)).isoformat(),
                "latitude": latitude, "longitude": longitude,
                "maxradiuskm": radius, "orderby": "time", "limit": 10
            })
            payload = connector.fetch_json(
                "https://earthquake.usgs.gov/fdsnws/event/1/query?" + parameters
            )
            features = payload.get("features") or []
            feature = features[0] if features else {}
        properties = feature.get("properties") or {}
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        observed = {
            "found": bool(feature), "event_id": feature.get("id"),
            "magnitude": properties.get("mag"), "status": properties.get("status"),
            "alert_level": properties.get("alert"),
            "tsunami": bool(properties.get("tsunami")) if feature else None,
            "place": properties.get("place"),
            "longitude": coordinates[0] if len(coordinates)>0 else None,
            "latitude": coordinates[1] if len(coordinates)>1 else None,
            "updated_at": properties.get("updated")
        }
        return payload, observed, bool(event_id)

    def _nws(self, connector, query):
        alert_id = str(query.get("alert_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9._-]{3,200}", alert_id):
            raise ValueError("Invalid NWS alert identifier")
        payload = connector.fetch_json(
            "https://api.weather.gov/alerts/" + urllib.parse.quote(alert_id, safe="")
        )
        props = payload.get("properties") or {}
        observed = {
            "found": bool(props), "alert_id": alert_id,
            "status": props.get("status") or props.get("messageType"),
            "alert_level": props.get("severity"), "event": props.get("event"),
            "expires": props.get("expires"), "area": props.get("areaDesc")
        }
        return payload, observed, True

    def _cisa(self, connector, query):
        cve = str(query.get("cve") or "").upper()
        if not re.fullmatch(r"CVE-\d{4}-\d{4,}", cve):
            raise ValueError("Invalid CVE identifier")
        payload = connector.fetch_json(connector.base_url)
        match = next((row for row in payload.get("vulnerabilities", [])
                      if str(row.get("cveID") or "").upper()==cve), None)
        observed = {
            "found": bool(match), "cve": cve, "known_exploited": bool(match),
            "date_added": (match or {}).get("dateAdded"),
            "due_date": (match or {}).get("dueDate"),
            "ransomware_use": (match or {}).get("knownRansomwareCampaignUse")
        }
        return {"catalogVersion":payload.get("catalogVersion"),"match":match}, observed, True

    def _github(self, connector, query):
        key = "cve_id" if query.get("cve") else "ghsa_id"
        value = str(query.get("cve") or query.get("ghsa") or "").upper()
        pattern = r"CVE-\d{4}-\d{4,}" if key=="cve_id" else r"GHSA-[A-Z0-9-]{14}"
        if not re.fullmatch(pattern, value):
            raise ValueError("Invalid advisory identifier")
        url = connector.base_url + "?" + urllib.parse.urlencode({key:value,"per_page":10})
        payload = connector.fetch_json(url)
        rows = payload if isinstance(payload,list) else payload.get("advisories",[])
        match = rows[0] if rows else None
        observed = {
            "found": bool(match), "cve": (match or {}).get("cve_id"),
            "ghsa": (match or {}).get("ghsa_id"),
            "severity": (match or {}).get("severity"),
            "withdrawn_at": (match or {}).get("withdrawn_at")
        }
        return {"match":match}, observed, True

    def _world_bank(self, connector, query):
        country = _code(query.get("country"), 2, 3)
        indicator = _code(query.get("indicator"), 3, 40, dots=True)
        year = str(query.get("year") or "")
        if not re.fullmatch(r"\d{4}", year):
            raise ValueError("Invalid World Bank observation year")
        path = "/".join((connector.base_url,urllib.parse.quote(country,safe=""),
                         "indicator",urllib.parse.quote(indicator,safe="")))
        payload = connector.fetch_json(
            path+"?"+urllib.parse.urlencode({"format":"json","date":year,"per_page":10})
        )
        rows = payload[1] if isinstance(payload,list) and len(payload)>1 else []
        match = rows[0] if rows else None
        observed = {"found":bool(match),"country":country,"indicator":indicator,
                    "year":year,"value":(match or {}).get("value")}
        return {"metadata":payload[0] if rows else {},"match":match}, observed, True

    def _fred(self, connector, query):
        series = _code(query.get("series_id"), 1, 80, dots=True)
        date = str(query.get("date") or "")
        parameters={"series_id":series,"api_key":connector.api_key,
                    "file_type":"json","sort_order":"desc","limit":10}
        if date:
            parameters.update({"observation_start":date,"observation_end":date})
        payload=connector.fetch_json(connector.base_url+"?"+urllib.parse.urlencode(parameters))
        rows=payload.get("observations",[]); match=rows[0] if rows else None
        observed={"found":bool(match),"series_id":series,"date":(match or {}).get("date"),
                  "value":(match or {}).get("value")}
        return {"match":match},observed,bool(date)


def compare_observation(expected, observed, closed_world=False):
    predicate = str(expected.get("predicate") or "")
    expected_value = expected.get("normalized_value") or expected.get("value")
    if not observed.get("found"):
        if closed_world and predicate in {"cyber.known_exploited","event.active_alert"}:
            return "refutes", "", .9, "Exact authoritative catalog lookup found no matching record."
        return "inconclusive", "", .3, "No exact authoritative record was found; absence is not treated as falsity."
    key = {
        "seismic.magnitude":"magnitude", "event.status":"status",
        "event.alert_level":"alert_level", "economic.value":"value",
        "cyber.known_exploited":"known_exploited"
    }.get(predicate)
    if not key:
        return "supports", "", .92, "An exact authoritative record exists for the typed identifier."
    actual = observed.get(key)
    expected_number = _number(expected_value)
    actual_number = _number(actual)
    if expected_number is not None and actual_number is not None:
        tolerance = .05 if predicate=="seismic.magnitude" else max(.001,abs(expected_number)*.001)
        if math.isclose(expected_number,actual_number,abs_tol=tolerance):
            return "supports", "", .97, "Authoritative numeric value matches within the defined tolerance."
        if predicate in {"seismic.magnitude","economic.value"}:
            return "revises", "authoritative-value-revision", .96, "The authoritative source now reports a materially revised value."
        return "refutes", "", .96, "The authoritative numeric value conflicts with the claim."
    if _normalize(actual)==_normalize(expected_value):
        return "supports", "", .96, "The authoritative value matches the normalized claim."
    return "revises", "authoritative-status-revision", .92, "The authoritative record now reports a different status or value."


def _bounded_snapshot(value, maximum=12000):
    encoded=json.dumps(value,sort_keys=True,default=str,separators=(",",":"))
    if len(encoded)<=maximum: return json.loads(encoded)
    return {"truncated":True,"preview":encoded[:maximum]}


def _parse_time(value):
    try: return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(UTC)
    except (TypeError,ValueError): return None


def _bounded_float(value,minimum,maximum):
    number=float(value)
    if not minimum<=number<=maximum: raise ValueError("Numeric lookup parameter outside allowed range")
    return number


def _code(value,minimum,maximum,dots=False):
    value=str(value or "").upper()
    pattern=r"[A-Z0-9._-]+" if dots else r"[A-Z0-9_-]+"
    if not minimum<=len(value)<=maximum or not re.fullmatch(pattern,value):
        raise ValueError("Invalid authoritative lookup code")
    return value


def _number(value):
    try:
        match=re.search(r"[-+]?\d+(?:\.\d+)?",str(value))
        return float(match.group(0)) if match else None
    except (TypeError,ValueError): return None


def _normalize(value): return re.sub(r"\s+"," ",str(value or "").strip().lower())
