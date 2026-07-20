import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from agent.events import Event


class NtfyObserver:
    def __init__(self):
        self.provider = os.getenv("ENTITY_NOTIFY_PROVIDER", "").lower()
        self.base_url = os.getenv("ENTITY_NTFY_URL", "https://ntfy.sh")
        self.topic = os.getenv("ENTITY_NTFY_IN_TOPIC", "")
        self.token = os.getenv("ENTITY_NTFY_TOKEN", "")
        self.event_bus = None
        self.running = False
        self.thread = None

    def start(self, event_bus):
        self.event_bus = event_bus

        if not self.available():
            return

        self.running = True
        self.thread = threading.Thread(
            target=self._run,
            daemon=True
        )
        self.thread.start()

    def stop(self):
        self.running = False

        if self.thread:
            self.thread.join(timeout=2)

    def available(self):
        return (
            self.provider == "ntfy"
            and bool(self.base_url)
            and bool(self.topic)
        )

    def _run(self):
        while self.running:
            try:
                self._listen_once()
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                if self.running:
                    time.sleep(5)

    def _listen_once(self):
        request = urllib.request.Request(self._stream_url())
        self._add_auth(request)

        with urllib.request.urlopen(request, timeout=90) as response:
            for raw_line in response:
                if not self.running:
                    return

                line = raw_line.decode("utf-8").strip()

                if not line:
                    continue

                event = json.loads(line)

                if event.get("event") != "message":
                    continue

                title = event.get("title", "")

                if title.startswith("Entity"):
                    continue

                message = event.get("message", "").strip()

                if not message:
                    continue

                self.event_bus.publish(
                    Event(
                        source="ntfy",
                        type="remote_message",
                        payload={
                            "text": message,
                            "title": title,
                            "channel": "remote"
                        },
                        priority=5
                    )
                )

    def _stream_url(self):
        topic_url = urllib.parse.urljoin(
            self.base_url.rstrip("/") + "/",
            urllib.parse.quote(self.topic)
        )
        return topic_url.rstrip("/") + "/json"

    def _add_auth(self, request):
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
