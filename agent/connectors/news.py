import hashlib
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree

from agent.connectors.mail_common import clean_html, normalize_mail_time
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class NewsFeedConnector:
    """Read publisher-supplied RSS or Atom metadata without scraping articles."""

    kind = "traditional_news"
    poll_seconds = 300

    def __init__(
        self,
        name,
        feed_url,
        credibility=0.8,
        timeout=15,
        max_items=50,
        poll_seconds=300,
        fetch_xml=None,
        enabled=True
    ):
        self.name = str(name or "News feed").strip()
        self.base_url = str(feed_url or "").strip()
        digest = hashlib.sha256(self.base_url.encode("utf-8")).hexdigest()[:12]
        self.source_id = f"news_rss_{digest}"
        self.credibility = max(0.0, min(1.0, float(credibility)))
        self.timeout = max(1, int(timeout))
        self.max_items = max(1, int(max_items))
        self.poll_seconds = max(60, int(poll_seconds))
        self._fetch_xml_override = fetch_xml
        self.enabled = bool(enabled and self.base_url)

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})

        root = ElementTree.fromstring(self._fetch_xml())
        nodes = root.findall("./channel/item")
        if not nodes:
            nodes = [node for node in root.iter() if _local_name(node.tag) == "entry"]

        items = [self._normalize(node) for node in nodes[:self.max_items]]
        items = [item for item in items if item.url]
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "newest_external_id": items[0].external_id if items else None
        })

    def _normalize(self, node):
        title = _child_text(node, "title") or f"{self.name} report"
        url = _entry_url(node)
        external_id = (
            _child_text(node, "guid")
            or _child_text(node, "id")
            or _stable_id(url, title)
        )
        summary = _clean_feed_text(
            _child_text(node, "description")
            or _child_text(node, "summary")
            or _child_text(node, "content")
        )
        published = (
            _child_text(node, "pubDate")
            or _child_text(node, "published")
            or _child_text(node, "updated")
        )
        categories = _categories(node)
        domain = urllib.parse.urlsplit(url).hostname or ""
        return SourceItem(
            external_id=external_id,
            title=_clean_feed_text(title),
            url=url,
            summary=summary,
            published_at=normalize_mail_time(published),
            category="traditional-news",
            metadata={
                "publisher": self.name,
                "domain": domain.lower(),
                "feed_url": self.base_url,
                "author": _child_text(node, "creator") or _child_text(node, "author"),
                "feed_categories": categories,
                "content_scope": "publisher_feed_metadata"
            }
        )

    def _fetch_xml(self):
        if self._fetch_xml_override is not None:
            return self._fetch_xml_override(self.base_url)
        request = urllib.request.Request(self.base_url, headers={
            "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml",
            "User-Agent": "EntityIntelligence/0.1 (read-only public news feed)"
        })
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read()


def _local_name(tag):
    return str(tag).rsplit("}", 1)[-1]


def _child_text(node, name):
    for child in node:
        if _local_name(child.tag).lower() != name.lower():
            continue
        return "".join(child.itertext()).strip()
    return ""


def _entry_url(node):
    for child in node:
        if _local_name(child.tag).lower() != "link":
            continue
        href = str(child.attrib.get("href") or "").strip()
        relation = str(child.attrib.get("rel") or "alternate").lower()
        if href and relation in {"alternate", ""}:
            return href
        text = "".join(child.itertext()).strip()
        if text:
            return text
    return ""


def _categories(node):
    values = []
    for child in node:
        if _local_name(child.tag).lower() != "category":
            continue
        value = str(child.attrib.get("term") or "").strip()
        value = value or "".join(child.itertext()).strip()
        if value and value not in values:
            values.append(value)
    return values


def _stable_id(url, title):
    return hashlib.sha256(f"{url}\n{title}".encode("utf-8")).hexdigest()


def _clean_feed_text(value):
    return re.sub(r"\s+([.,;:!?])", r"\1", clean_html(value))
