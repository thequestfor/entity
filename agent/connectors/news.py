import hashlib
import gzip
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree

from agent.connectors.mail_common import clean_html, normalize_mail_time
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.source_registry import SourcePolicy
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
        article_acquisition_mode="feed-only",
        article_hosts=(),
        article_requests_per_cycle=2,
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
        mode = str(article_acquisition_mode or "feed-only").strip().lower()
        self.article_acquisition_mode = (
            mode if mode in {"feed-only", "publisher-page"} else "feed-only"
        )
        feed_host = urllib.parse.urlsplit(self.base_url).hostname or ""
        self.article_hosts = tuple(
            sorted({str(value).lower().strip() for value in article_hosts if value})
        ) or ((feed_host.lower(),) if feed_host else ())
        self.source_policy = SourcePolicy(
            "public", "journalistic", "report", f"publisher:{digest}",
            (feed_host.lower(),) if feed_host else (),
            "Publisher terms require review", self.base_url, self.name,
            "local-analysis-review-required", False, "publisher coverage", "minutes",
            ("RSS metadata is discovery; article retrieval requires explicit policy.",),
            article_acquisition_mode=self.article_acquisition_mode,
            article_hosts=self.article_hosts,
            article_max_bytes=2_000_000,
            article_requests_per_cycle=max(
                1, min(25, int(article_requests_per_cycle))
            ),
            article_excerpt_display=True,
        )
        self.enabled = bool(enabled and self.base_url)

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})

        root = _parse_feed_xml(self._fetch_xml())
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
        description = _child_text(node, "description") or _child_text(node, "summary")
        supplied_content = _clean_feed_text(_child_text(node, "content"))
        summary = _clean_feed_text(description or supplied_content)
        full_content = supplied_content if len(supplied_content) >= 500 else ""
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
            content=full_content,
            published_at=normalize_mail_time(published),
            category="traditional-news",
            metadata={
                "publisher": self.name,
                "domain": domain.lower(),
                "feed_url": self.base_url,
                "author": _child_text(node, "creator") or _child_text(node, "author"),
                "feed_categories": categories,
                "content_scope": (
                    "publisher_feed_full_content" if full_content
                    else "publisher_feed_metadata"
                )
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


def _parse_feed_xml(payload):
    if isinstance(payload, str):
        text = payload
    else:
        raw = bytes(payload or b"")
        if raw.startswith(b"\x1f\x8b"):
            raw = gzip.decompress(raw)
        text = raw.decode("utf-8-sig", errors="replace")
    start = text.find("<")
    if start < 0:
        raise ValueError("News feed response did not contain XML.")
    text = text[start:]
    # XML 1.0 rejects most control characters. A single publisher-side bad
    # byte should not disable an otherwise valid feed.
    text = re.sub(
        "[\\x00-\\x08\\x0B\\x0C\\x0E-\\x1F\\uFFFE\\uFFFF]", "", text
    )
    root = ElementTree.fromstring(text)
    if _local_name(root.tag).lower() not in {"rss", "feed", "rdf"}:
        raise ValueError("News endpoint did not return an RSS or Atom feed.")
    return root


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
