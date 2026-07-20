import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter


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


class CalendarIntentExtractor:
    def __init__(self, router=None, fallback_parser=None):
        self.router = router or ModelRouter()
        self.fallback_parser = fallback_parser or CalendarCommandParser()
        self.timezone = self.fallback_parser.timezone
        self.default_duration = self.fallback_parser.default_duration

    def extract(self, command, awareness_state=None, on_escalation=None):
        if not self.fallback_parser.looks_like_calendar_command(command):
            return None

        try:
            payload = self.router.generate_json(
                self._prompt(command, awareness_state),
                user_input=command,
                on_escalation=on_escalation,
                routing="calendar_extract"
            )
            return self._draft_from_payload(payload, command)
        except (ModelUnavailable, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return self.fallback_parser.parse(command)

    def _prompt(self, command, awareness_state):
        now = datetime.now(self.timezone).isoformat()
        state = awareness_state or {}

        return (
            "You extract Google Calendar event details for Entity. The user "
            "wants Entity to decide what calendar operation is needed, but "
            "you do not execute the operation. Return JSON only.\n\n"
            "If the user is not asking to create or schedule a calendar "
            "event, return intent=create_event with confidence 0.\n\n"
            "Rules:\n"
            "- Infer event title, date, time, recurrence, and location from "
            "the user text.\n"
            "- Use ISO dates, 24-hour HH:MM times, and IANA timezone.\n"
            "- If a weekly class is described, set recurrence.frequency to "
            "WEEKLY and include BYDAY such as MO.\n"
            "- If duration is not said, use duration_minutes "
            f"{self.default_duration}.\n"
            "- If essential fields are missing, set confidence below 0.7.\n"
            "- Do not invent a location if none was given.\n\n"
            "Return exactly this JSON shape:\n"
            "{\n"
            '  "intent": "create_event",\n'
            '  "confidence": 0.0,\n'
            '  "summary": "",\n'
            '  "date": "YYYY-MM-DD",\n'
            '  "time": "HH:MM",\n'
            f'  "timezone": "{self.timezone.key}",\n'
            '  "duration_minutes": 60,\n'
            '  "location": "",\n'
            '  "recurrence": {\n'
            '    "frequency": "",\n'
            '    "byday": ""\n'
            "  }\n"
            "}\n\n"
            f"Current local datetime: {now}\n"
            f"Awareness state: {json.dumps(state)}\n"
            f"User text: {command}"
        )

    def _draft_from_payload(self, payload, command):
        if payload.get("intent") != "create_event":
            return None

        confidence = float(payload.get("confidence", 0.0))

        if confidence < 0.7:
            raise ValueError("Calendar intent confidence too low.")

        summary = str(payload.get("summary", "")).strip()
        date_text = str(payload.get("date", "")).strip()
        time_text = str(payload.get("time", "")).strip()

        if not summary or not date_text or not time_text:
            raise ValueError("Calendar event missing required fields.")

        timezone = ZoneInfo(
            str(payload.get("timezone") or self.timezone.key)
        )
        start_date = datetime.fromisoformat(date_text).date()
        start_time = time.fromisoformat(time_text)
        start = datetime.combine(
            start_date,
            start_time,
            tzinfo=timezone
        )
        duration = int(
            payload.get("duration_minutes") or self.default_duration
        )
        end = start + timedelta(minutes=duration)
        recurrence = self._recurrence(payload.get("recurrence") or {})

        return CalendarEventDraft(
            summary=summary,
            start=start,
            end=end,
            location=str(payload.get("location", "")).strip(),
            description=f"Created by Entity from: {command}",
            recurrence=recurrence,
            source_text=command
        )

    def _recurrence(self, payload):
        frequency = str(payload.get("frequency", "")).upper().strip()
        byday = str(payload.get("byday", "")).upper().strip()

        if not frequency:
            return []

        if frequency != "WEEKLY":
            raise ValueError("Unsupported calendar recurrence.")

        if byday not in {value[0] for value in WEEKDAYS.values()}:
            raise ValueError("Unsupported weekly recurrence day.")

        return [f"RRULE:FREQ=WEEKLY;BYDAY={byday}"]


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

    def ready_for_background_reads(self):
        return (
            self.enabled
            and self.credentials_path.exists()
            and self.token_path.exists()
        )

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

    def get_event(self, event_id):
        if not self.enabled:
            raise RuntimeError("Google Calendar is disabled.")

        service = self._service()
        return (
            service.events()
            .get(
                calendarId=self.calendar_id,
                eventId=event_id
            )
            .execute()
        )

    def upcoming_events(self, hours=24):
        if not self.enabled:
            raise RuntimeError("Google Calendar is disabled.")

        service = self._service()
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=hours)
        result = (
            service.events()
            .list(
                calendarId=self.calendar_id,
                timeMin=now.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime"
            )
            .execute()
        )

        return result.get("items", [])

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
