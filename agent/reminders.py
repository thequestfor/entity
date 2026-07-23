import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter


@dataclass
class ReminderDraft:
    due_at: float
    message: str
    priority: int = 7


class ReminderIntentExtractor:
    def __init__(self, router=None, fallback_parser=None):
        self.router = router or ModelRouter()
        self.fallback_parser = fallback_parser or ReminderFallbackParser()
        self.timezone = self.fallback_parser.timezone

    def extract(self, command, awareness_state=None, on_escalation=None):
        if not self.looks_like_reminder(command):
            return None

        try:
            payload = self.router.generate_json(
                self._prompt(command, awareness_state),
                user_input=command,
                on_escalation=on_escalation,
                routing="reminder_extract"
            )
            return self._draft_from_payload(payload)
        except (ModelUnavailable, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return self.fallback_parser.parse(command)

    def looks_like_reminder(self, command):
        normalized = command.lower()

        if re.search(
            r"\b(?:why|how come)\s+(?:did|didn't|did not|haven't|have not)\b",
            normalized
        ):
            return False

        if re.search(
            r"\b(?:did you|have you|why didn't you|why did you not)\b",
            normalized
        ):
            return False

        return (
            "remind me" in normalized
            or "reminder" in normalized
            or "don't let me forget" in normalized
            or "wake me" in normalized
        )

    def _prompt(self, command, awareness_state):
        now = datetime.now(self.timezone).isoformat()
        state = awareness_state or {}

        return (
            "You extract reminder details for Entity. You do not schedule the "
            "reminder yourself. Return JSON only.\n\n"
            "Rules:\n"
            "- If the user is not asking to create a reminder, set confidence "
            "to 0.\n"
            "- Infer the reminder message and exact due time.\n"
            "- Use ISO 8601 datetime with timezone for due_at.\n"
            "- If the due time is ambiguous or missing, set confidence below "
            "0.7.\n"
            "- Priority should usually be 7. Use 9 for urgent reminders.\n\n"
            "Return exactly this JSON shape:\n"
            "{\n"
            '  "intent": "create_reminder",\n'
            '  "confidence": 0.0,\n'
            '  "message": "",\n'
            '  "due_at": "YYYY-MM-DDTHH:MM:SS-04:00",\n'
            '  "priority": 7\n'
            "}\n\n"
            f"Current local datetime: {now}\n"
            f"Awareness state: {json.dumps(state)}\n"
            f"User text: {command}"
        )

    def _draft_from_payload(self, payload):
        if payload.get("intent") != "create_reminder":
            return None

        confidence = float(payload.get("confidence", 0.0))

        if confidence < 0.7:
            raise ValueError("Reminder intent confidence too low.")

        message = str(payload.get("message", "")).strip()
        due_at_text = str(payload.get("due_at", "")).strip()

        if not message or not due_at_text:
            raise ValueError("Reminder missing required fields.")

        due = datetime.fromisoformat(due_at_text)

        if due.tzinfo is None:
            due = due.replace(tzinfo=self.timezone)

        if due <= datetime.now(due.tzinfo):
            raise ValueError("Reminder due time is in the past.")

        priority = self._priority(payload.get("priority", 7))

        return ReminderDraft(
            due_at=due.timestamp(),
            message=message,
            priority=priority
        )

    def _priority(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 7

        return min(10, max(1, value))


class ReminderFallbackParser:
    def __init__(self):
        self.timezone = ZoneInfo(
            os.getenv("ENTITY_TIMEZONE", "America/New_York")
        )

    def parse(self, command):
        return (
            self._parse_relative(command)
            or self._parse_wake(command)
            or self._parse_absolute(command)
        )

    def _parse_wake(self, command):
        match = re.search(
            r"\bwake me\s+"
            r"(?:up\s+)?"
            r"(?:(today|tomorrow|tonight|next\s+\w+)\s+)?"
            r"(?:at\s+)?"
            r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?"
            r"(?:\s+(today|tomorrow|tonight|next\s+\w+))?",
            command,
            re.IGNORECASE
        )

        if not match:
            return None

        day_phrase = match.group(1) or match.group(5)
        due = self._date_for_phrase(day_phrase).replace(
            hour=self._normalize_hour(int(match.group(2)), match.group(4)),
            minute=int(match.group(3) or 0),
            second=0,
            microsecond=0
        )

        if due <= self._now():
            due += timedelta(days=1)

        return ReminderDraft(
            due_at=due.timestamp(),
            message="Wake up",
            priority=9
        )

    def _parse_relative(self, command):
        pattern = re.compile(
            r"\bremind me in (\d+)\s+"
            r"(seconds|second|minutes|minute|hours|hour)"
            r"(?:\s+to\s+(.+))?",
            re.IGNORECASE
        )
        match = pattern.search(command)

        if not match:
            return None

        amount = int(match.group(1))
        unit = match.group(2).lower()
        message = (match.group(3) or "Reminder").strip()
        multiplier = 1

        if unit.startswith("minute"):
            multiplier = 60
        elif unit.startswith("hour"):
            multiplier = 3600

        return ReminderDraft(
            due_at=time.time() + (amount * multiplier),
            message=message,
            priority=7
        )

    def _parse_absolute(self, command):
        if re.search(r"\bremind me in\b", command, re.IGNORECASE):
            return None

        timed = re.search(
            r"\bremind me\s+"
            r"(?:(today|tomorrow|tonight|next\s+\w+)\s+)?"
            r"(?:at\s+)?"
            r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
            r"(?:\s+to\s+(.+))?",
            command,
            re.IGNORECASE
        )

        if timed:
            day_phrase = timed.group(1)
            hour = int(timed.group(2))
            minute = int(timed.group(3) or 0)
            meridiem = timed.group(4)
            message = (timed.group(5) or "Reminder").strip()
            due = self._date_for_phrase(day_phrase)
            due = due.replace(
                hour=self._normalize_hour(hour, meridiem),
                minute=minute,
                second=0,
                microsecond=0
            )

            if due <= self._now():
                due += timedelta(days=1)

            return ReminderDraft(
                due_at=due.timestamp(),
                message=message,
                priority=7
            )

        day_only = re.search(
            r"\bremind me\s+"
            r"(today|tomorrow|tonight|next\s+\w+)"
            r"(?:\s+(morning|afternoon|evening|night))?"
            r"(?:\s+to\s+(.+))?",
            command,
            re.IGNORECASE
        )

        if not day_only:
            return None

        day_phrase = day_only.group(1)
        part_of_day = day_only.group(2)
        message = (day_only.group(3) or "Reminder").strip()
        due = self._date_for_phrase(day_phrase).replace(
            hour=self._hour_for_part_of_day(part_of_day, day_phrase),
            minute=0,
            second=0,
            microsecond=0
        )

        if due <= self._now():
            due += timedelta(days=1)

        return ReminderDraft(
            due_at=due.timestamp(),
            message=message,
            priority=7
        )

    def _now(self):
        return datetime.now().astimezone()

    def _date_for_phrase(self, phrase):
        now = self._now()

        if not phrase or phrase.lower() == "today":
            return now

        phrase = phrase.lower().strip()

        if phrase == "tomorrow":
            return now + timedelta(days=1)

        if phrase == "tonight":
            return now

        if phrase.startswith("next "):
            target = self._weekday_number(
                phrase.replace("next ", "", 1).strip()
            )

            if target is not None:
                days_ahead = (target - now.weekday()) % 7

                if days_ahead == 0:
                    days_ahead = 7

                return now + timedelta(days=days_ahead)

        return now

    def _weekday_number(self, weekday):
        return {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6
        }.get(weekday)

    def _normalize_hour(self, hour, meridiem):
        if meridiem:
            meridiem = meridiem.lower().replace(".", "")

            if meridiem == "pm" and hour != 12:
                return hour + 12

            if meridiem == "am" and hour == 12:
                return 0

        return hour

    def _hour_for_part_of_day(self, part_of_day, day_phrase=None):
        if not part_of_day:
            if day_phrase and day_phrase.lower().strip() == "tonight":
                return 21

            return 9

        return {
            "morning": 9,
            "afternoon": 13,
            "evening": 18,
            "night": 21
        }.get(part_of_day.lower(), 9)
