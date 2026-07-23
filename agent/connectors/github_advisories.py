from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class GitHubAdvisoriesConnector(JsonConnector):
    """Collect public GitHub Security Advisories without repository access."""

    source_id = "github_security_advisories"
    name = "GitHub Security Advisories"
    kind = "cybersecurity"
    base_url = "https://api.github.com/advisories"
    credibility = 0.9
    poll_seconds = 3600

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})

        payload = self.fetch_json(f"{self.base_url}?per_page={self.max_items}")
        advisories = payload if isinstance(payload, list) else payload.get("advisories", [])
        items = []
        for advisory in advisories[:self.max_items]:
            advisory_id = str(advisory.get("ghsa_id") or advisory.get("cve_id") or "")
            url = str(advisory.get("html_url") or "").strip()
            if not advisory_id or not url:
                continue
            items.append(SourceItem(
                external_id=advisory_id,
                title=str(advisory.get("summary") or advisory_id),
                url=url,
                summary=str(advisory.get("description") or ""),
                published_at=advisory.get("published_at"),
                category="software-vulnerability",
                metadata={
                    "provider": "GitHub Security Advisories",
                    "ghsa_id": advisory.get("ghsa_id"),
                    "cve_id": advisory.get("cve_id"),
                    "severity": advisory.get("severity"),
                    "updated_at": advisory.get("updated_at"),
                    "withdrawn_at": advisory.get("withdrawn_at"),
                    "cvss": advisory.get("cvss"),
                    "cwes": advisory.get("cwes")
                }
            ))
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "newest_external_id": items[0].external_id if items else None
        })
