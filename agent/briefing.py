import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from agent.calendar import GoogleCalendarClient
from agent.memory.store import MemoryStore
from agent.routes import RoutePlanner


class TodayBriefing:
    def __init__(
        self,
        calendar_client=None,
        route_planner=None,
        store=None
    ):
        self.calendar_client = calendar_client or GoogleCalendarClient()
        self.route_planner = route_planner or RoutePlanner()
        self.store = store or MemoryStore()

    def build(self):
        lines = [
            self._opening()
        ]
        calendar_lines = self._calendar_lines()
        reminder_lines = self._reminder_lines()

        if calendar_lines:
            lines.extend(calendar_lines)
        else:
            lines.append("No upcoming calendar events found for today.")

        if reminder_lines:
            lines.extend(reminder_lines)
        else:
            lines.append("No pending reminders.")

        return " ".join(lines)

    def _opening(self):
        now = datetime.now(self._timezone())
        return f"Today is {now.strftime('%A, %B %d')}."

    def _calendar_lines(self):
        if not self.calendar_client.ready_for_background_reads():
            return [
                "Google Calendar is not ready for briefing."
            ]

        try:
            events = self.calendar_client.upcoming_events(hours=24)
        except Exception as exc:
            return [
                f"Google Calendar briefing unavailable: {exc}."
            ]

        lines = []

        for item in events[:5]:
            start = item.get("start", {}).get("dateTime")

            if not start:
                continue

            start_dt = datetime.fromisoformat(start).astimezone(
                self._timezone()
            )
            summary = item.get("summary", "Calendar event")
            location = item.get("location", "")
            line = f"{summary} at {start_dt.strftime('%-I:%M %p')}"

            if location:
                line += f" at {location}"

            route_line = self._route_line(
                {
                    "summary": summary,
                    "location": location,
                    "start": start_dt.isoformat()
                }
            )

            if route_line:
                line += f". {route_line}"
            else:
                line += "."

            lines.append(line)

        return lines

    def _route_line(self, event_payload):
        if not event_payload.get("location"):
            return ""

        try:
            advice = self.route_planner.departure_advice(event_payload)
        except Exception:
            return ""

        if not advice:
            return ""

        parts = advice.split(". ")

        if len(parts) <= 1:
            return advice

        return ". ".join(parts[1:])

    def _reminder_lines(self):
        now = datetime.now(self._timezone()).timestamp()
        tomorrow = (
            datetime.now(self._timezone()) + timedelta(hours=24)
        ).timestamp()
        tasks = [
            task
            for task in self.store.pending_tasks()
            if task["due_at"] <= tomorrow
        ]

        if not tasks:
            return []

        lines = [
            f"Pending reminders today: {len(tasks)}."
        ]

        for task in tasks[:3]:
            due = datetime.fromtimestamp(
                task["due_at"],
                tz=self._timezone()
            )
            label = "overdue" if task["due_at"] < now else due.strftime("%-I:%M %p")
            lines.append(f"{task['message']} at {label}.")

        return lines

    def _timezone(self):
        return ZoneInfo(
            os.getenv("ENTITY_TIMEZONE", "America/New_York")
        )
