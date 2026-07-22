import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from agent.calendar import GoogleCalendarClient
from agent.events import Event
from agent.routes import RoutePlanner


class CalendarObserver:
    def __init__(self, client=None, route_planner=None):
        self.client = client or GoogleCalendarClient()
        self.route_planner = route_planner or RoutePlanner()
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
        self.route_cache = {}
        self.route_refresh_seconds = self._env_int(
            "ENTITY_ROUTE_REFRESH_SECONDS",
            default=900,
            minimum=60
        )
        self.route_check_horizon_hours = self._env_int(
            "ENTITY_ROUTE_CHECK_HORIZON_HOURS",
            default=4,
            minimum=1
        )

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

            if not self._within_alert_window(payload):
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

    def _within_alert_window(self, payload):
        start_dt = datetime.fromisoformat(payload["start"])
        now = datetime.now(self.timezone)

        if not now <= start_dt:
            return False

        lead_seconds = self.alert_lead_minutes * 60
        route_seconds = self._route_duration(payload, now, start_dt)

        if route_seconds is not None:
            lead_seconds = (
                route_seconds
                + self.route_planner.buffer_minutes * 60
            )

        alert_at = start_dt - timedelta(seconds=lead_seconds)
        return now >= alert_at

    def _route_duration(self, payload, now, start_dt):
        location = payload.get("location", "")

        if not location or not self.route_planner.available():
            return None

        horizon = timedelta(hours=self.route_check_horizon_hours)

        if start_dt - now > horizon:
            return None

        key = self._instance_key(payload)
        cached = self.route_cache.get(key)

        if cached and time.time() - cached["checked_at"] < self.route_refresh_seconds:
            return cached["duration_seconds"]

        try:
            estimate = self.route_planner.estimate(
                self.route_planner.home_address,
                location
            )
        except Exception as exc:
            print("Calendar route check failed:", exc)
            return None

        self.route_cache[key] = {
            "checked_at": time.time(),
            "duration_seconds": estimate.duration_seconds
        }
        return estimate.duration_seconds

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

    def _env_int(self, name, default, minimum):
        try:
            value = int(os.getenv(name, str(default)))
        except ValueError:
            value = default

        return max(minimum, value)
