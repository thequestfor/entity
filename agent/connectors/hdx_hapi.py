"""Bounded humanitarian needs and operational-presence observations."""

import hashlib
import urllib.parse

from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


THEMES = {
    "affected-people/humanitarian-needs": "humanitarian-needs",
    "coordination-context/operational-presence": "humanitarian-presence"
}


class HdxHapiConnector(JsonConnector):
    source_id = "hdx_hapi"
    name = "HDX Humanitarian API"
    kind = "humanitarian_measurement"
    base_url = "https://hapi.humdata.org/api/v1"
    credibility = 0.92
    poll_seconds = 21600

    def __init__(self, app_identifier="", locations=(), themes=tuple(THEMES),
                 **kwargs):
        super().__init__(**kwargs)
        self.app_identifier = str(app_identifier or "").strip()
        self.locations = tuple(
            str(item).strip().upper() for item in locations
            if len(str(item).strip()) == 3
        )[:50]
        self.themes = tuple(item for item in themes if item in THEMES)[:4]
        self.enabled = self.enabled and bool(
            self.app_identifier and self.locations and self.themes
        )

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})
        items = []
        per_request = max(1, min(1000, self.max_items))
        for theme in self.themes:
            for location in self.locations:
                remaining = self.max_items - len(items)
                if remaining <= 0:
                    break
                params = urllib.parse.urlencode({
                    "location_code":location,"output_format":"json",
                    "offset":0,"limit":min(per_request,remaining),
                    "app_identifier":self.app_identifier
                })
                try:
                    payload = self.fetch_json(f"{self.base_url}/{theme}?{params}")
                except Exception as exc:
                    raise RuntimeError("HDX HAPI request failed") from exc
                for record in (payload.get("data") or [])[:remaining]:
                    item = _item(theme, record)
                    if item:
                        items.append(item)
            if len(items) >= self.max_items:
                break
        return ConnectorBatch(items=items,cursor={
            "retrieved_at":utc_now(),"locations":list(self.locations),
            "themes":list(self.themes)
        })


def _item(theme, record):
    location = str(record.get("admin2_name") or record.get("admin1_name") or record.get("location_name") or "").strip()
    country = str(record.get("location_name") or "").strip()
    resource = str(record.get("resource_hdx_id") or record.get("dataset_hdx_id") or "").strip()
    if not resource or not country:
        return None
    category = THEMES[theme]
    sector = str(record.get("sector_name") or "").strip()
    organization = str(record.get("org_name") or record.get("org_acronym") or "").strip()
    population = record.get("population")
    status = str(record.get("population_status") or "").strip()
    period = str(record.get("reference_period_end") or record.get("hapi_updated_date") or "").strip()
    identity = {
        "theme":theme,"resource":resource,"location":record.get("location_code"),
        "admin1":record.get("admin1_code"),"admin2":record.get("admin2_code"),
        "sector":sector,"organization":organization,"status":status,"period":period
    }
    external_id = hashlib.sha256(
        repr(sorted(identity.items())).encode()
    ).hexdigest()
    if category == "humanitarian-needs":
        title = f"Humanitarian needs in {location or country}"
        summary = f"{population or 'Reported population'} {status or 'people'} for {sector or 'all sectors'}."
    else:
        title = f"Humanitarian operational presence in {location or country}"
        summary = f"{organization or 'An organization'} reports activity in {sector or 'an unspecified sector'}."
    dataset_stub = str(record.get("dataset_hdx_stub") or "").strip()
    dataset_id = str(record.get("dataset_hdx_id") or "").strip()
    if dataset_id:
        base = f"https://data.humdata.org/dataset/{urllib.parse.quote(dataset_id)}/resource/{urllib.parse.quote(resource)}"
    else:
        base = f"https://data.humdata.org/dataset/{urllib.parse.quote(dataset_stub or resource)}"
    url = f"{base}?hapi_record={external_id}"
    return SourceItem(
        external_id=external_id,title=title,url=str(url),summary=summary,
        published_at=period or None,category=category,
        metadata={
            **identity,"country":country,"country_code":record.get("location_code") or "",
            "admin1_name":record.get("admin1_name") or "",
            "admin2_name":record.get("admin2_name") or "",
            "population":population,"population_status":status,
            "dataset_hdx_id":record.get("dataset_hdx_id") or "",
            "dataset_hdx_stub":dataset_stub,"resource_hdx_id":resource,
            "reporting_sources":[record.get("provider_name")] if record.get("provider_name") else [],
            "epistemic_type":"humanitarian-measurement"
        }
    )
