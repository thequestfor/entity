import re
import time
from datetime import datetime, timedelta

from agent.actuators import (
    CalendarActuator,
    DiagnosticsActuator,
    NotifyActuator,
    SpeechActuator
)
from agent.attention import ImportancePolicy
from agent.awareness import AwarenessLoop
from agent.calendar import CalendarIntentExtractor
from agent.event_bus import EventBus
from agent.events import Action
from agent.math_tools import ArithmeticHandler
from agent.observers import (
    AudioObserver,
    CalendarObserver,
    NtfyObserver,
    SchedulerObserver
)
from agent.policy import Policy
from agent.routes import RoutePlanner


class EntityRuntime:
    def __init__(
        self,
        brain=None,
        awareness=None,
        audio_observer=None,
        scheduler_observer=None,
        importance_policy=None,
        calendar_extractor=None,
        arithmetic_handler=None,
        route_planner=None,
        observers=None,
        actuators=None,
        policy=None
    ):
        self.brain = brain or self._default_brain()
        self.awareness = awareness or AwarenessLoop(
            on_interrupt=self.publish_event
        )
        self.event_bus = EventBus()
        self.scheduler_observer = (
            scheduler_observer or SchedulerObserver()
        )
        self.task_store = self.scheduler_observer.store
        self.importance_policy = importance_policy or ImportancePolicy()
        self.calendar_extractor = calendar_extractor or CalendarIntentExtractor()
        self.arithmetic_handler = arithmetic_handler or ArithmeticHandler()
        self.route_planner = route_planner or RoutePlanner()
        self.observers = observers or [
            self.scheduler_observer,
            CalendarObserver(),
            NtfyObserver(),
            audio_observer or AudioObserver()
        ]
        self.actuators = actuators or [
            CalendarActuator(),
            DiagnosticsActuator(),
            NotifyActuator(),
            SpeechActuator()
        ]
        self.policy = policy or Policy()

    def run(self):
        self.start()

        try:
            while True:
                event = self.event_bus.next_event()

                if event:
                    self.handle_event(event)

                self.event_bus.task_done()

        finally:
            self.stop()

    def start(self):
        self.awareness.start()

        for observer in self.observers:
            observer.start(self.event_bus)

        self.execute(
            Action(
                type="speak",
                payload={
                    "text": "Systems online"
                }
            )
        )
        self._alert_if_no_language_model()

    def stop(self):
        self.awareness.stop()

        for observer in self.observers:
            observer.stop()

    def publish_event(self, event):
        self.event_bus.publish(event)

    def handle_event(self, event):
        self._record_event(event)

        if event.type == "user_speech":
            return self.handle_text_input(event, channel="voice")

        if event.type == "remote_message":
            return self.handle_text_input(event, channel="remote")

        if event.type == "reminder":
            return self.handle_reminder(event)

        if event.type == "calendar_event_upcoming":
            return self.handle_calendar_event_upcoming(event)

        if event.message:
            return self.handle_observed_event(event)

        return None

    def _default_brain(self):
        from agent.brain import Brain

        return Brain()

    def handle_user_speech(self, event):
        return self.handle_text_input(event, channel="voice")

    def handle_text_input(self, event, channel="voice"):
        command = event.payload.get("text", "")

        if not command:
            return None

        if channel == "remote":
            print("Remote:", command)
        else:
            print("Heard:", command)

        self.awareness.record_input(command)

        runtime_response = self._handle_runtime_command(
            command,
            source=channel
        )

        if runtime_response:
            self.awareness.record_response(runtime_response)
            self._reply(runtime_response, channel)
            print(runtime_response)
            return runtime_response

        response_stream = self.brain.respond_stream(
            command,
            self.awareness.snapshot(),
            on_escalation=lambda message: self._reply(message, channel)
        )

        if channel == "remote":
            response = "".join(response_stream)
            self._reply(response, channel)
        else:
            action = Action(
                type="speak",
                payload={
                    "stream": response_stream
                }
            )

            response = self.execute(action)

        self.awareness.record_response(response)

        print(response)

        return response

    def handle_reminder(self, event):
        message = event.message

        if not message:
            return None

        decision = self.importance_policy.evaluate(
            event,
            awareness_state=self.awareness.snapshot()
        )

        self.execute(
            Action(
                type="speak",
                payload={
                    "text": message
                }
            )
        )

        if decision.should_notify:
            self.execute(
                Action(
                    type="notify",
                    payload={
                        "title": "Entity reminder",
                        "text": message,
                        "priority": "high"
                    }
                )
            )

        return message

    def handle_calendar_event_upcoming(self, event):
        message = event.message

        try:
            route_message = self.route_planner.departure_advice(event.payload)
        except Exception as exc:
            print("Route planning failed:", exc)
            route_message = None

        if route_message:
            message = route_message

        if not message:
            return None

        self.execute(
            Action(
                type="speak",
                payload={
                    "text": message
                }
            )
        )
        self.execute(
            Action(
                type="notify",
                payload={
                    "title": "Entity departure alert",
                    "text": message,
                    "priority": "high"
                }
            )
        )

        return message

    def handle_observed_event(self, event):
        decision = self.importance_policy.evaluate(
            event,
            awareness_state=self.awareness.snapshot()
        )

        if decision.should_notify:
            return self.execute(
                Action(
                    type="notify",
                    payload={
                        "title": "Entity alert",
                        "text": event.message,
                        "priority": "high"
                    }
                )
            )

        if decision.decision in {"act", "ask"}:
            return self.execute(
                Action(
                    type="speak",
                    payload={
                        "text": event.message
                    }
                )
            )

        return None

    def _alert_if_no_language_model(self):
        decision = self.importance_policy.model_health_decision()

        if not decision.should_notify:
            return None

        message = decision.reason
        self.execute(
            Action(
                type="speak",
                payload={
                    "text": message
                }
            )
        )
        self.execute(
            Action(
                type="notify",
                payload={
                    "title": "Entity system alert",
                    "text": message,
                    "priority": "urgent"
                }
            )
        )

        return message

    def _record_event(self, event):
        try:
            self.task_store.add_event(event)
        except Exception as exc:
            print("Failed to record event:", exc)

    def _reply(self, text, channel):
        if not text:
            return None

        if channel == "remote":
            return self.execute(
                Action(
                    type="notify",
                    payload={
                        "title": "Entity",
                        "text": text
                    }
                )
            )

        return self.execute(
            Action(
                type="speak",
                payload={
                    "text": text
                }
            )
        )

    def _handle_runtime_command(self, command, source="voice"):
        if self._is_diagnostics_command(command):
            return self.execute(
                Action(
                    type="diagnostics",
                    payload={
                        "runtime": self
                    }
                )
            )

        voice_response = self._handle_voice_command(command)

        if voice_response:
            return voice_response

        math_response = self.arithmetic_handler.answer(command)

        if math_response:
            return math_response

        calendar_response = self._handle_calendar_command(
            command,
            channel=source
        )

        if calendar_response:
            return calendar_response

        reminder = self._parse_reminder(command)

        if not reminder:
            return None

        due_at, message = reminder
        task_id = self.task_store.add_task(
            title=message,
            message=message,
            due_at=due_at,
            kind="reminder",
            priority=7,
            source=source
        )

        self.scheduler_observer.add_reminder_at(
            due_at,
            message,
            task_id=task_id
        )

        response = f"Reminder set: {message}."

        return response

    def _handle_calendar_command(self, command, channel="voice"):
        draft = self.calendar_extractor.extract(
            command,
            awareness_state=self.awareness.snapshot(),
            on_escalation=lambda message: self._reply(message, channel)
        )

        if draft is None:
            return None

        return self.execute(
            Action(
                type="calendar",
                payload={
                    "operation": "create_event",
                    "draft": draft
                }
            )
        )

    def _parse_reminder(self, command):
        relative = self._parse_relative_reminder(command)

        if relative:
            return relative

        absolute = self._parse_absolute_reminder(command)

        if absolute:
            return absolute

        return None

    def _parse_relative_reminder(self, command):
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

        return time.time() + (amount * multiplier), message

    def _parse_absolute_reminder(self, command):
        if re.search(r"\bremind me in\b", command, re.IGNORECASE):
            return None

        patterns = [
            re.compile(
                r"\bremind me\s+"
                r"(?:(today|tomorrow|tonight|next\s+\w+)\s+)?"
                r"(?:at\s+)?"
                r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
                r"(?:\s+to\s+(.+))?",
                re.IGNORECASE
            ),
            re.compile(
                r"\bremind me\s+"
                r"(today|tomorrow|tonight|next\s+\w+)"
                r"(?:\s+(morning|afternoon|evening|night))?"
                r"(?:\s+to\s+(.+))?",
                re.IGNORECASE
            )
        ]

        timed = patterns[0].search(command)

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

            return due.timestamp(), message

        day_only = patterns[1].search(command)

        if day_only:
            day_phrase = day_only.group(1)
            part_of_day = day_only.group(2)
            message = (day_only.group(3) or "Reminder").strip()
            hour = self._hour_for_part_of_day(
                part_of_day,
                day_phrase=day_phrase
            )
            due = self._date_for_phrase(day_phrase).replace(
                hour=hour,
                minute=0,
                second=0,
                microsecond=0
            )

            if due <= self._now():
                due += timedelta(days=1)

            return due.timestamp(), message

        return None

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
            weekday = phrase.replace("next ", "", 1).strip()
            target = self._weekday_number(weekday)

            if target is not None:
                days_ahead = (target - now.weekday()) % 7

                if days_ahead == 0:
                    days_ahead = 7

                return now + timedelta(days=days_ahead)

        return now

    def _weekday_number(self, weekday):
        weekdays = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6
        }

        return weekdays.get(weekday)

    def _normalize_hour(self, hour, meridiem):
        if meridiem:
            meridiem = meridiem.lower()

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

        hours = {
            "morning": 9,
            "afternoon": 13,
            "evening": 18,
            "night": 21
        }

        return hours.get(part_of_day.lower(), 9)

    def _handle_voice_command(self, command):
        normalized = command.lower().strip()

        if (
            "what voice" in normalized
            or "which voice" in normalized
            or "current voice" in normalized
        ):
            from tts.manager import get_voice

            response = f"Current voice: {get_voice()}."

            return response

        pattern = re.compile(
            r"\b(?:use|switch to|set|change to)\s+"
            r"(?:the\s+)?(kokoro|sam)"
            r"(?:\s+voice)?\b",
            re.IGNORECASE
        )
        match = pattern.search(command)

        if not match:
            return None

        voice = match.group(1).lower()

        from tts.manager import set_voice

        set_voice(voice)

        response = f"Voice set to {voice}."

        return response

    def _is_diagnostics_command(self, command):
        normalized = command.lower()

        return (
            "diagnostic" in normalized
            or "system status" in normalized
            or "status report" in normalized
        )

    def execute(self, action):
        if not self.policy.allows(action):
            print(
                "Action blocked by policy:",
                action.type
            )
            return None

        for actuator in self.actuators:
            if actuator.can_handle(action):
                return actuator.execute(action)

        print(
            "No actuator for action:",
            action.type
        )

        return None
