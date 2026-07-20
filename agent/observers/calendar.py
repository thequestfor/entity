import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from agent.calendar import GoogleCalendarClient
from agent.events import Event


class CalendarObserver:
    def __init__(self, client=None):
        self.client = client or GoogleCalendarClient()
        self.event_bus = None
        self.running = False
        self.thread = None
        self.poll_seconds = int(
            os.getenv("ENTITY_CALENDAR_POLL_SECONDS", "300")
        )
        self.lookahead_hours = int(
            os.getenv("ENTITY_CALENDAR_LOOKAHEAD_HOURS", "24")
        )
        self.alert_lead_minutes = int(
            os.getenv("ENTITY_CALENDAR_ALERT_LEAD_MINUTES", "30")
        )
        self.timezone = ZoneInfo(
            os.getenv("ENTITY_TIMEZONE", "America/New_York")
        )
        self.seen_instances = set()

    def start(self, event_bus):
        self.event_bus = event_bus

        if not self.client.ready_for_background_reads():
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

    def _run(self):
        while self.running:
            try:
                self._poll()
            except Exception as exc:
                print("Calendar observer error:", exc)

            self._sleep()

    def _poll(self):
        for item in self.client.upcoming_events(hours=self.lookahead_hours):
            payload = self._event_payload(item)

            if payload is None:
                continue

            if not self._within_alert_window(payload["start"]):
                continue

            instance_key = self._instance_key(payload)

            if instance_key in self.seen_instances:
                continue

            self.seen_instances.add(instance_key)

            self.event_bus.publish(
                Event(
                    source="google_calendar",
                    type="calendar_event_upcoming",
                    payload=payload,
                    priority=7
                )
            )

    def _event_payload(self, item):
        start = item.get("start", {}).get("dateTime")
        end = item.get("end", {}).get("dateTime")

        if not start:
            return None

        summary = item.get("summary", "Calendar event")
        location = item.get("location", "")
        start_dt = datetime.fromisoformat(start).astimezone(self.timezone)
        end_dt = None

        if end:
            end_dt = datetime.fromisoformat(end).astimezone(self.timezone)

        message = self._message(summary, start_dt, location)

        return {
            "message": message,
            "summary": summary,
            "location": location,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat() if end_dt else "",
            "event_id": item.get("id", ""),
            "calendar_id": self.client.calendar_id,
            "html_link": item.get("htmlLink", "")
        }

    def _within_alert_window(self, start):
        start_dt = datetime.fromisoformat(start)
        now = datetime.now(self.timezone)
        lead = now + timedelta(minutes=self.alert_lead_minutes)

        return now <= start_dt <= lead

    def _instance_key(self, payload):
        return (
            payload.get("event_id", ""),
            payload.get("start", "")
        )

    def _message(self, summary, start, location):
        when = start.strftime("%-I:%M %p")

        if location:
            return f"Upcoming calendar event: {summary} at {when} at {location}."

        return f"Upcoming calendar event: {summary} at {when}."

    def _sleep(self):
        deadline = time.time() + self.poll_seconds

        while self.running and time.time() < deadline:
            time.sleep(min(1, deadline - time.time()))
