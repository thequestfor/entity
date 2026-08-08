"""Authenticated, bounded access to ACLED's curated conflict event API."""

import json
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.source_registry import validate_connector_url
from agent.intelligence.store import utc_now


class AcledConnector:
    source_id = "acled_conflict"
    name = "Armed Conflict Location & Event Data"
    kind = "conflict_event"
    base_url = "https://acleddata.com/api/acled/read"
    token_url = "https://acleddata.com/oauth/token"
    credibility = 0.9
    poll_seconds = 900

    def __init__(self, username="", password="", lookback_days=7, timeout=15,
                 max_items=50, fetch_json=None, enabled=False):
        self.username = str(username or "").strip()
        self.password = str(password or "")
        self.lookback_days = max(1, min(30, int(lookback_days)))
        self.timeout = max(1, int(timeout))
        self.max_items = max(1, min(500, int(max_items)))
        self._fetch_json_override = fetch_json
        self.enabled = bool(enabled and self.username and self.password)
        self._token = ""
        self._token_expires_at = 0.0

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})
        start = (datetime.now(UTC) - timedelta(days=self.lookback_days)).date()
        end = datetime.now(UTC).date()
        fields = (
            "event_id_cnty|event_date|time_precision|disorder_type|event_type|"
            "sub_event_type|actor1|actor2|civilian_targeting|iso|country|admin1|"
            "admin2|location|latitude|longitude|geo_precision|source|source_scale|"
            "notes|fatalities|tags|timestamp"
        )
        params = urllib.parse.urlencode({
            "_format":"json","event_date":f"{start}|{end}",
            "event_date_where":"BETWEEN","fields":fields,
            "limit":self.max_items,"page":1
        })
        payload = self._fetch(f"{self.base_url}?{params}")
        if payload.get("success") is False:
            raise RuntimeError("ACLED API rejected the bounded event request")
        items = []
        for event in (payload.get("data") or [])[:self.max_items]:
            external_id = str(event.get("event_id_cnty") or "").strip()
            if not external_id:
                continue
            latitude = _number(event.get("latitude"), -90, 90)
            longitude = _number(event.get("longitude"), -180, 180)
            event_type = str(event.get("event_type") or "Conflict event").strip()
            sub_type = str(event.get("sub_event_type") or "").strip()
            location = str(event.get("location") or event.get("admin1") or event.get("country") or "").strip()
            notes = str(event.get("notes") or "").strip()
            fatalities = _integer(event.get("fatalities"))
            title = f"{sub_type or event_type} in {location or 'reported location'}"
            items.append(SourceItem(
                external_id=external_id,title=title,
                url=("https://acleddata.com/data-export-tool/?event_id_cnty="
                     + urllib.parse.quote(external_id)),
                summary=notes[:2000],content=notes[:20_000],
                published_at=_event_time(event),category="conflict",
                latitude=latitude,longitude=longitude,
                metadata={
                    "event_type":event_type,"sub_event_type":sub_type,
                    "disorder_type":event.get("disorder_type") or "",
                    "actor1":event.get("actor1") or "","actor2":event.get("actor2") or "",
                    "civilian_targeting":event.get("civilian_targeting") or "",
                    "fatalities":fatalities,"fatalities_status":"reported-conservative-estimate",
                    "country":event.get("country") or "","country_code":"",
                    "country_numeric_code":event.get("iso") or "",
                    "admin1":event.get("admin1") or "","admin2":event.get("admin2") or "",
                    "location":location,"geo_precision":event.get("geo_precision"),
                    "time_precision":event.get("time_precision"),
                    "reporting_sources":_split_sources(event.get("source")),
                    "source_scale":event.get("source_scale") or "",
                    "tags":event.get("tags") or "","acled_timestamp":event.get("timestamp"),
                    "epistemic_type":"curated-reported-event",
                    "geometry":{"type":"Point","coordinates":[longitude,latitude]}
                    if latitude is not None and longitude is not None else {}
                }
            ))
        newest = max((_integer(item.metadata.get("acled_timestamp")) for item in items), default=0)
        return ConnectorBatch(items=items,cursor={
            "retrieved_at":utc_now(),"newest_acled_timestamp":newest,
            "lookback_days":self.lookback_days
        })

    def _fetch(self, url):
        validate_connector_url(self, url)
        if self._fetch_json_override is not None:
            return self._fetch_json_override(url)
        token = self._access_token()
        request = urllib.request.Request(url, headers={
            "Accept":"application/json","Authorization":f"Bearer {token}",
            "User-Agent":"EntityIntelligence/0.1 (bounded read-only ACLED client)"
        })
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))

    def _access_token(self):
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        body = urllib.parse.urlencode({
            "username":self.username,"password":self.password,
            "grant_type":"password","client_id":"acled","scope":"authenticated"
        }).encode()
        request = urllib.request.Request(self.token_url, data=body, headers={
            "Accept":"application/json","Content-Type":"application/x-www-form-urlencoded",
            "User-Agent":"EntityIntelligence/0.1 (ACLED OAuth client)"
        })
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        token = str(payload.get("access_token") or "")
        if not token:
            raise RuntimeError("ACLED authentication did not return an access token")
        self._token = token
        self._token_expires_at = time.monotonic() + max(60, int(payload.get("expires_in") or 3600) - 60)
        return token


def _number(value, minimum, maximum):
    try:
        value = float(value)
        return value if minimum <= value <= maximum else None
    except (TypeError, ValueError):
        return None


def _integer(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _event_time(event):
    value = str(event.get("event_date") or "").strip()
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).isoformat()
    except ValueError:
        return None


def _split_sources(value):
    return [item.strip() for item in str(value or "").split(";") if item.strip()]
