import os

from agent.models.cloud_openai import CloudOpenAIProvider
from agent.models.router import ModelRouter
from agent.routes import RoutePlanner


class StartupHealthCheck:
    def __init__(self, router=None):
        self.router = router or ModelRouter()

    def issues(self):
        issues = []

        issues.extend(self._model_issues())
        issues.extend(self._notification_issues())
        issues.extend(self._calendar_issues())
        issues.extend(self._route_issues())

        return issues

    def alert_message(self):
        issues = self.issues()

        if not issues:
            return ""

        return (
            "Startup diagnostic found service issues. "
            + " ".join(issues)
        )

    def _model_issues(self):
        if self.router.provider() is not None:
            return []

        return [
            "No language model is available."
        ]

    def _notification_issues(self):
        provider = os.getenv("ENTITY_NOTIFY_PROVIDER", "").lower()

        if provider != "ntfy":
            return []

        issues = []

        if not os.getenv("ENTITY_NTFY_OUT_TOPIC"):
            issues.append("Ntfy outbound topic is missing.")

        if not os.getenv("ENTITY_NTFY_IN_TOPIC"):
            issues.append("Ntfy inbound topic is missing.")

        return issues

    def _calendar_issues(self):
        enabled = self._env_bool("ENTITY_GOOGLE_CALENDAR_ENABLED")

        if not enabled:
            return []

        from agent.calendar import GoogleCalendarClient

        client = GoogleCalendarClient()
        issues = []

        if not client.credentials_path.exists():
            issues.append("Google Calendar credentials are missing.")

        if not client.token_path.exists():
            issues.append("Google Calendar OAuth token is missing.")

        return issues

    def _route_issues(self):
        planner = RoutePlanner()

        if planner.provider != "openrouteservice":
            return []

        issues = []

        if not planner.api_key:
            issues.append("Openrouteservice API key is missing.")

        if not planner.home_address:
            issues.append("Home address is missing for route planning.")

        return issues

    def _env_bool(self, name):
        return os.getenv(name, "").lower().strip() in {
            "1",
            "true",
            "yes",
            "on"
        }
