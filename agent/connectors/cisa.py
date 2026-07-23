from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class CisaKevConnector(JsonConnector):
    """Collect CISA's public catalog of known exploited vulnerabilities."""

    source_id = "cisa_known_exploited_vulnerabilities"
    name = "CISA Known Exploited Vulnerabilities"
    kind = "cybersecurity"
    base_url = (
        "https://www.cisa.gov/sites/default/files/feeds/"
        "known_exploited_vulnerabilities.json"
    )
    credibility = 1.0
    poll_seconds = 21600

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})

        payload = self.fetch_json(self.base_url)
        items = []
        for vulnerability in payload.get("vulnerabilities", [])[:self.max_items]:
            cve = str(vulnerability.get("cveID") or "").strip()
            if not cve:
                continue
            vendor = str(vulnerability.get("vendorProject") or "Unknown vendor")
            product = str(vulnerability.get("product") or "unknown product")
            description = str(vulnerability.get("shortDescription") or "")
            required_action = str(vulnerability.get("requiredAction") or "")
            summary = description
            if required_action:
                summary = f"{summary}\n\nRequired action: {required_action}".strip()
            items.append(SourceItem(
                external_id=cve,
                title=f"{cve}: {vendor} {product}",
                url=f"https://www.cisa.gov/known-exploited-vulnerabilities-catalog?search_api_fulltext={cve}",
                summary=summary,
                published_at=vulnerability.get("dateAdded"),
                category="known-exploited-vulnerability",
                metadata={
                    "cve": cve,
                    "vendor": vendor,
                    "product": product,
                    "date_added": vulnerability.get("dateAdded"),
                    "due_date": vulnerability.get("dueDate"),
                    "known_ransomware_campaign_use": (
                        vulnerability.get("knownRansomwareCampaignUse")
                    ),
                    "notes": vulnerability.get("notes"),
                    "provider": "US Cybersecurity and Infrastructure Security Agency"
                }
            ))
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "catalog_version": payload.get("catalogVersion"),
            "count": len(items)
        })
