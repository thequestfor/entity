import hashlib
import urllib.request
import xml.etree.ElementTree as ElementTree

from agent.connectors.mail_common import clean_html, normalize_mail_time
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class GdacsConnector:
    source_id = "gdacs"
    name = "Global Disaster Alert and Coordination System"
    kind = "natural_hazard"
    base_url = "https://www.gdacs.org/xml/rss_24h.xml"
    credibility = 0.95
    poll_seconds = 360

    def __init__(self, timeout=15, max_items=50, fetch_xml=None, enabled=True):
        self.timeout = max(1, int(timeout))
        self.max_items = max(1, int(max_items))
        self._fetch_xml_override = fetch_xml
        self.enabled = bool(enabled)

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})

        root = ElementTree.fromstring(self._fetch_xml())
        items = []
        for node in root.findall("./channel/item")[:self.max_items]:
            title = _text(node, "title") or "GDACS disaster alert"
            url = _text(node, "link")
            external_id = _text(node, "guid") or _stable_id(url, title)
            alert_level = _namespaced_text(node, "alertlevel")
            event_type = _namespaced_text(node, "eventtype")
            latitude, longitude = _point(node)
            items.append(SourceItem(
                external_id=external_id,
                title=title,
                url=url,
                summary=clean_html(_text(node, "description")),
                published_at=normalize_mail_time(_text(node, "pubDate")),
                category=_event_category(event_type),
                latitude=latitude,
                longitude=longitude,
                metadata={
                    "alert_level": alert_level,
                    "event_type": event_type,
                    "country": _namespaced_text(node, "country"),
                    "severity": _namespaced_text(node, "severity")
                }
            ))

        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "newest_external_id": items[0].external_id if items else None
        })

    def _fetch_xml(self):
        if self._fetch_xml_override is not None:
            return self._fetch_xml_override(self.base_url)
        request = urllib.request.Request(self.base_url, headers={
            "Accept": "application/rss+xml, application/xml, text/xml",
            "User-Agent": "EntityIntelligence/0.1 (read-only public feed)"
        })
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read()


def _text(node, tag):
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _namespaced_text(node, local_name):
    for child in node:
        if child.tag.rsplit("}", 1)[-1].lower() == local_name.lower():
            return (child.text or "").strip()
    return ""


def _point(node):
    value = _namespaced_text(node, "point")
    try:
        latitude, longitude = value.split()[:2]
        return float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None, None


def _stable_id(url, title):
    return hashlib.sha256(f"{url}\n{title}".encode("utf-8")).hexdigest()


def _event_category(event_type):
    return {
        "EQ": "earthquake",
        "TC": "severe-storms",
        "FL": "floods",
        "WF": "wildfires",
        "VO": "volcanoes",
        "DR": "drought"
    }.get(str(event_type or "").upper(), "disaster-alert")
