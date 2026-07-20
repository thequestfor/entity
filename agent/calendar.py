import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


WEEKDAYS = {
    "monday": ("MO", 0),
    "tuesday": ("TU", 1),
    "wednesday": ("WE", 2),
    "thursday": ("TH", 3),
    "friday": ("FR", 4),
    "saturday": ("SA", 5),
    "sunday": ("SU", 6)
}


@dataclass
class CalendarEventDraft:
    summary: str
    start: datetime
    end: datetime
    location: str = ""
    description: str = ""
    recurrence: list[str] = field(default_factory=list)
    source_text: str = ""

    def to_google_event(self):
        timezone = self.start.tzinfo.key
        event = {
            "summary": self.summary,
            "start": {
                "dateTime": self.start.isoformat(),
                "timeZone": timezone
            },
            "end": {
                "dateTime": self.end.isoformat(),
                "timeZone": timezone
            }
        }

        if self.location:
            event["location"] = self.location

        if self.description:
            event["description"] = self.description

        if self.recurrence:
            event["recurrence"] = self.recurrence

        return event

    def to_dict(self):
        data = asdict(self)
        data["start"] = self.start.isoformat()
        data["end"] = self.end.isoformat()
        return data


class CalendarCommandParser:
    def __init__(self):
        self.timezone = ZoneInfo(
            os.getenv("ENTITY_TIMEZONE", "America/New_York")
        )
        self.default_duration = int(
            os.getenv("ENTITY_CALENDAR_DEFAULT_EVENT_MINUTES", "60")
        )

    def parse(self, command):
        return (
            self._parse_weekly_event(command)
            or self._parse_single_event(command)
        )

    def looks_like_calendar_command(self, command):
        normalized = command.lower()

        return (
            "calendar" in normalized
            or "schedule" in normalized
            or "every week" in normalized
            or "weekly" in normalized
            or "i have" in normalized
        )

    def _parse_weekly_event(self, command):
        pattern = re.compile(
            r"(?:remember\s+)?"
            r"(?:that\s+)?"
            r"(?:i\s+have\s+)?"
            r"(?P<title>.+?)\s+"
            r"(?:every\s+week|weekly)\s+"
            r"(?:on\s+|at\s+)?"
            r"(?P<weekday>monday|tuesday|wednesday|thursday|friday|"
            r"saturday|sunday)\s+"
            r"(?:at\s+)?"
            r"(?P<hour>\d{1,2})"
            r"(?::(?P<minute>\d{2}))?\s*"
            r"(?P<meridiem>am|pm)?"
            r"(?:\s+(?:at|in)\s+(?P<location>.+))?",
            re.IGNORECASE
        )
        match = pattern.search(command)

        if not match:
            return None

        weekday = match.group("weekday").lower()
        byday, weekday_number = WEEKDAYS[weekday]
        start = self._next_datetime(
            weekday_number,
            int(match.group("hour")),
            int(match.group("minute") or 0),
            match.group("meridiem")
        )
        end = start + timedelta(minutes=self.default_duration)
        summary = self._clean_summary(match.group("title"))

        return CalendarEventDraft(
            summary=summary,
            start=start,
            end=end,
            location=(match.group("location") or "").strip(),
            description=f"Created by Entity from: {command}",
            recurrence=[f"RRULE:FREQ=WEEKLY;BYDAY={byday}"],
            source_text=command
        )

    def _parse_single_event(self, command):
        pattern = re.compile(
            r"(?:add|schedule|put)\s+"
            r"(?P<title>.+?)\s+"
            r"(?:to\s+)?(?:my\s+)?calendar\s+"
            r"(?:today|on\s+today)?\s*"
            r"(?:at\s+)?"
            r"(?P<hour>\d{1,2})"
            r"(?::(?P<minute>\d{2}))?\s*"
            r"(?P<meridiem>am|pm)?"
            r"(?:\s+(?:at|in)\s+(?P<location>.+))?",
            re.IGNORECASE
        )
        match = pattern.search(command)

        if not match:
            return None

        now = datetime.now(self.timezone)
        start = now.replace(
            hour=self._normalize_hour(
                int(match.group("hour")),
                match.group("meridiem")
            ),
            minute=int(match.group("minute") or 0),
            second=0,
            microsecond=0
        )

        if start <= now:
            start += timedelta(days=1)

        return CalendarEventDraft(
            summary=self._clean_summary(match.group("title")),
            start=start,
            end=start + timedelta(minutes=self.default_duration),
            location=(match.group("location") or "").strip(),
            description=f"Created by Entity from: {command}",
            source_text=command
        )

    def _next_datetime(self, weekday, hour, minute, meridiem):
        now = datetime.now(self.timezone)
        target = now.replace(
            hour=self._normalize_hour(hour, meridiem),
            minute=minute,
            second=0,
            microsecond=0
        )
        days_ahead = (weekday - now.weekday()) % 7

        if days_ahead == 0 and target <= now:
            days_ahead = 7

        return target + timedelta(days=days_ahead)

    def _normalize_hour(self, hour, meridiem):
        if meridiem:
            meridiem = meridiem.lower()

            if meridiem == "pm" and hour != 12:
                return hour + 12

            if meridiem == "am" and hour == 12:
                return 0

        return hour

    def _clean_summary(self, title):
        title = re.sub(
            r"^(remember\s+)?(that\s+)?(i\s+have\s+)?",
            "",
            title.strip(),
            flags=re.IGNORECASE
        )
        return title.strip(" .") or "Calendar event"


class GoogleCalendarClient:
    scopes = [
        "https://www.googleapis.com/auth/calendar.events"
    ]

    def __init__(self):
        self.enabled = self._env_bool("ENTITY_GOOGLE_CALENDAR_ENABLED")
        self.calendar_id = os.getenv(
            "ENTITY_GOOGLE_CALENDAR_ID",
            "primary"
        )
        self.credentials_path = Path(
            os.getenv(
                "ENTITY_GOOGLE_CREDENTIALS_PATH",
                "agent/google_credentials.json"
            )
        )
        self.token_path = Path(
            os.getenv(
                "ENTITY_GOOGLE_TOKEN_PATH",
                "agent/google_token.json"
            )
        )

    def available(self):
        return self.enabled and self.credentials_path.exists()

    def setup_status(self):
        if not self.enabled:
            return "Google Calendar disabled."

        if not self.credentials_path.exists():
            return (
                "Google Calendar enabled but credentials file is missing."
            )

        if not self.token_path.exists():
            return (
                "Google Calendar credentials present. OAuth token has not "
                "been created yet."
            )

        return "Google Calendar configured."

    def insert_event(self, draft):
        if not self.enabled:
            raise RuntimeError("Google Calendar is disabled.")

        if not self.credentials_path.exists():
            raise RuntimeError(
                "Google Calendar credentials file is missing."
            )

        service = self._service()
        return (
            service.events()
            .insert(
                calendarId=self.calendar_id,
                body=draft.to_google_event()
            )
            .execute()
        )

    def _service(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Google Calendar dependencies are missing."
            ) from exc

        creds = None

        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(self.token_path),
                self.scopes
            )

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path),
                    self.scopes
                )
                creds = flow.run_local_server(port=0)

            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json())

        return build("calendar", "v3", credentials=creds)

    def _env_bool(self, name):
        value = os.getenv(name, "")

        return value.lower().strip() in {
            "1",
            "true",
            "yes",
            "on"
        }
