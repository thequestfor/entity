import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from agent.calendar import GoogleCalendarClient
from agent.intelligence.config import IntelligenceConfig
from agent.intelligence.store import IntelligenceStore
from agent.memory.store import MemoryStore
from agent.routes import RoutePlanner
from agent.weather import WeatherTool


class TodayBriefing:
    def __init__(
        self,
        calendar_client=None,
        route_planner=None,
        store=None,
        weather_tool=None,
        intelligence_store=None
    ):
        self.calendar_client = calendar_client or GoogleCalendarClient()
        self.route_planner = route_planner or RoutePlanner()
        self.store = store or MemoryStore()
        self.weather_tool = weather_tool or WeatherTool()
        self.intelligence_store = intelligence_store
        if self.intelligence_store is None:
            config = IntelligenceConfig.from_env()
            if config.enabled:
                self.intelligence_store = IntelligenceStore(
                    config.database_path
                )

    def build(self):
        lines = [
            self._opening()
        ]
        calendar_lines = self._calendar_lines()
        reminder_lines = self._reminder_lines()
        weather_line = self._weather_line()
        intelligence_lines = self._intelligence_lines()

        if weather_line:
            lines.append(weather_line)

        if calendar_lines:
            lines.extend(calendar_lines)
        else:
            lines.append("No upcoming calendar events found for today.")

        if reminder_lines:
            lines.extend(reminder_lines)
        else:
            lines.append("No pending reminders.")

        lines.extend(intelligence_lines)

        return " ".join(lines)

    def _weather_line(self):
        if not self.weather_tool.available():
            return ""
        return self.weather_tool.lookup(
            question="What should I wear today?"
        )

    def _intelligence_lines(self):
        if self.intelligence_store is None:
            return []
        try:
            briefing = self.intelligence_store.latest_briefing()
        except Exception:
            return ["World-intelligence briefing is temporarily unavailable."]
        if not briefing:
            return ["No world-intelligence briefing is available yet."]

        content = briefing.get("content") or {}
        lines = [
            "World intelligence: "
            + str(content.get("headline") or "No material updates summarized.")
        ]
        situations = content.get("situations") or []
        situations = [
            item for item in situations
            if item.get("status") == "contested"
            or int(item.get("source_count") or 0) >= 2
        ]
        titles = [
            str(item.get("title") or "").strip()
            for item in situations[:2]
            if str(item.get("title") or "").strip()
        ]
        if titles:
            lines.append("Leading updates: " + "; ".join(titles) + ".")
        conclusions = [
            str(item.get("worldview") or "").strip()
            for item in situations[:3]
            if str(item.get("worldview") or "").strip()
        ]
        if conclusions:
            lines.append(
                "World-model conclusions: " + " ".join(conclusions)
            )

        if hasattr(self.intelligence_store, "list_documents"):
            news = self.intelligence_store.list_documents(
                limit=3, category="traditional-news"
            )
            news_titles = [item["title"] for item in news if item.get("title")]
            if news_titles:
                lines.append(
                    "News watch: " + "; ".join(news_titles) + "."
                )
            markets = self.intelligence_store.list_documents(
                limit=50, category="prediction-market"
            )
            market_lines = []
            seen_market_titles = set()
            for item in markets:
                title = str(item.get("title") or "").strip()
                if (
                    not title or not item.get("summary")
                    or self._sports_market(item)
                    or title.lower() in seen_market_titles
                ):
                    continue
                seen_market_titles.add(title.lower())
                market_lines.append(f"{title} — {item['summary']}")
                if len(market_lines) >= 2:
                    break
            if market_lines:
                lines.append(
                    "Prediction-market signals: "
                    + " ".join(market_lines)
                )
        return lines

    def _sports_market(self, item):
        metadata = item.get("metadata") or {}
        text = " ".join((
            str(item.get("title") or ""),
            str(metadata.get("event_title") or "")
        )).lower()
        markers = (
            " nba", "nfl", "mlb", "nhl", "wnba", "fifa", "uefa",
            "champions league", "world cup", " vs. ", " vs ", "o/u ",
            "spread:", "moneyline", "goals scored", "points scored",
            "tennis", "ufc", "boxing", "lol:"
        )
        return any(marker in f" {text}" for marker in markers)

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
