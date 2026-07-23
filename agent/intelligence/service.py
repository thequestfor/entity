import ipaddress

from agent.intelligence.config import IntelligenceConfig
from agent.intelligence.store import IntelligenceStore
from agent.intelligence.web import IntelligenceDashboard
from agent.intelligence.worker import IntelligenceWorker


class IntelligenceService:
    def __init__(
        self,
        config=None,
        store=None,
        worker=None,
        dashboard=None
    ):
        self.config = config or IntelligenceConfig.from_env()
        self.enabled = bool(self.config.enabled)
        self.store = store
        self.worker = worker
        self.dashboard = dashboard

        if not self.enabled:
            return

        if (
            self.config.dashboard_enabled
            and (self.config.gmail_enabled or self.config.outlook_enabled)
            and not _is_loopback(self.config.dashboard_host)
        ):
            raise RuntimeError(
                "Private mail intelligence requires a localhost dashboard host."
            )

        self.store = self.store or IntelligenceStore(
            self.config.database_path
        )
        self.worker = self.worker or IntelligenceWorker.from_config(
            self.store,
            self.config
        )

        if self.config.dashboard_enabled:
            self.dashboard = self.dashboard or IntelligenceDashboard(
                store=self.store,
                host=self.config.dashboard_host,
                port=self.config.dashboard_port
            )

    @classmethod
    def from_env(cls):
        return cls(IntelligenceConfig.from_env())

    def start(self):
        if not self.enabled:
            return

        if self.dashboard:
            self.dashboard.start()

        self.worker.start()

    def stop(self):
        if not self.enabled:
            return

        if self.worker:
            self.worker.stop()

        if self.dashboard:
            self.dashboard.stop()

    def set_activity_callback(self, callback):
        if self.worker:
            self.worker.on_activity = callback

    def setup_status(self):
        if not self.enabled:
            return "World intelligence service disabled."

        overview = self.store.overview()
        worker = "online" if self.worker and self.worker.running else "stopped"
        dashboard = (
            self.dashboard.url
            if self.dashboard and self.dashboard.running
            else "disabled or stopped"
        )
        return (
            "World intelligence service enabled. "
            f"Worker {worker}. "
            f"Documents: {overview['documents']}. "
            f"Situations: {overview['situations']}. "
            f"Contested claims: {overview['contested_claims']}. "
            f"Sources: {overview['sources']}. "
            f"Dashboard: {dashboard}."
            + self._mail_status()
            + self._x_status()
            + self._signal_status()
        )

    def _mail_status(self):
        details = []
        if self.config.gmail_enabled:
            if not self.config.gmail_credentials_path.is_file():
                details.append(" Gmail credentials missing.")
            elif not self.config.gmail_token_path.is_file():
                details.append(" Gmail authorization token missing.")
            else:
                details.append(" Gmail read-only connector configured.")
        if self.config.outlook_enabled:
            if not self.config.outlook_client_id:
                details.append(" Outlook client ID missing.")
            elif not self.config.outlook_token_cache_path.is_file():
                details.append(" Outlook authorization token missing.")
            else:
                details.append(" Outlook read-only connector configured.")
        return "".join(details)

    def _x_status(self):
        if not self.config.x_enabled:
            return ""
        if not self.config.x_bearer_token:
            return " X connector enabled but Bearer Token missing."
        if not (self.config.x_usernames or self.config.x_search_queries):
            return " X connector enabled but no accounts or queries selected."
        return (
            " X read-only connector configured for "
            f"{len(self.config.x_usernames)} account(s) and "
            f"{len(self.config.x_search_queries)} search query(s)."
        )

    def _signal_status(self):
        details = []
        if self.config.news_enabled:
            details.append(
                f" {len(self.config.news_rss_feeds)} traditional news feed(s) configured."
            )
        if self.config.polymarket_enabled:
            details.append(" Polymarket public forecast signals configured.")
        return "".join(details)


def _is_loopback(host):
    host = str(host or "").strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
