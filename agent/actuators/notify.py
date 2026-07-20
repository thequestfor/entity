import os
import urllib.error
import urllib.parse
import urllib.request


class NotifyActuator:
    action_type = "notify"

    def __init__(self):
        self.provider = os.getenv("ENTITY_NOTIFY_PROVIDER", "").lower()
        self.base_url = os.getenv("ENTITY_NTFY_URL", "https://ntfy.sh")
        self.topic = os.getenv("ENTITY_NTFY_OUT_TOPIC", "")
        self.token = os.getenv("ENTITY_NTFY_TOKEN", "")

    def can_handle(self, action):
        return action.type == self.action_type

    def execute(self, action):
        if not self.available():
            return None

        text = action.payload.get("text", "")
        title = action.payload.get("title", "Entity")
        priority = str(action.payload.get("priority", "default"))

        if not text:
            return None

        request = urllib.request.Request(
            self._topic_url(),
            data=text.encode("utf-8"),
            method="POST",
            headers={
                "Title": title,
                "Priority": priority
            }
        )
        self._add_auth(request)

        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
            return text
        except (OSError, urllib.error.URLError):
            return None

    def available(self):
        return (
            self.provider == "ntfy"
            and bool(self.base_url)
            and bool(self.topic)
        )

    def _topic_url(self):
        return urllib.parse.urljoin(
            self.base_url.rstrip("/") + "/",
            urllib.parse.quote(self.topic)
        )

    def _add_auth(self, request):
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
