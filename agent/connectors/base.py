import json
import urllib.request


class JsonConnector:
    source_id = "unknown"
    name = "Unknown source"
    kind = "public_api"
    base_url = ""
    credibility = 0.5
    poll_seconds = 900

    def __init__(
        self,
        timeout=15,
        max_items=50,
        fetch_json=None,
        enabled=True
    ):
        self.timeout = max(1, int(timeout))
        self.max_items = max(1, int(max_items))
        self._fetch_json_override = fetch_json
        self.enabled = bool(enabled)

    def poll(self, cursor=None):
        raise NotImplementedError

    def fetch_json(self, url):
        if self._fetch_json_override is not None:
            return self._fetch_json_override(url)

        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "EntityIntelligence/0.1 "
                    "(local read-only intelligence service)"
                )
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=self.timeout
        ) as response:
            body = response.read().decode("utf-8", errors="replace")

        return json.loads(body)
