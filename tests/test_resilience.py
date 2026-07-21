import os
import io
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np

from agent.audio.frames import WakeFrameBuffer
from agent.event_bus import EventBus
from agent.health import StartupHealthCheck
from agent.lifecycle import Lifecycle
from agent.math_tools import ArithmeticHandler
from agent.memory.store import MemoryStore
from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter
from agent.observers.audio import AudioObserver
from agent.observers.calendar import CalendarObserver
from agent.observers.scheduler import SchedulerObserver
from agent.events import Event
from agent.runtime import EntityRuntime
from agent.speech.queue import SpeechQueue


class ResilienceTests(unittest.TestCase):
    def test_speech_worker_survives_playback_failure(self):
        calls = []

        def speaker(text):
            calls.append(text)

            if text == "fail":
                raise RuntimeError("synthetic failure")

        queue = SpeechQueue(speaker=speaker)

        try:
            queue.say("fail")

            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                queue.wait()

            self.assertTrue(queue.thread.is_alive())
            queue.say("recover")
            queue.wait()
            self.assertEqual(["fail", "recover"], calls)
        finally:
            queue.stop()

    def test_audio_observer_stop_unblocks_worker(self):
        class Microphone:
            def __init__(self):
                self.running = False
                self.wake = threading.Event()

            def start(self):
                self.running = True

            def stop(self):
                self.running = False
                self.wake.set()

            def wait_for_wake(self):
                self.wake.wait()
                return self.running

            def listen(self):
                return ""

        observer = AudioObserver(microphone=Microphone())
        observer.start(EventBus())
        observer.stop()

        self.assertFalse(observer.thread.is_alive())

    def test_scheduler_restart_does_not_duplicate_pending_tasks(self):
        with tempfile.TemporaryDirectory() as temp:
            store = MemoryStore(Path(temp) / "memory.db")
            store.add_task("test", "test", time.time() + 3600)
            scheduler = SchedulerObserver(store=store)

            scheduler.start(EventBus())
            scheduler.stop()
            scheduler.start(EventBus())

            try:
                self.assertEqual(1, len(scheduler.reminders))
            finally:
                scheduler.stop()

    def test_scheduler_keeps_task_pending_until_runtime_acknowledges_it(self):
        with tempfile.TemporaryDirectory() as temp:
            store = MemoryStore(Path(temp) / "memory.db")
            task_id = store.add_task("test", "test", time.time() - 1)
            scheduler = SchedulerObserver(store=store)
            scheduler.event_bus = EventBus()
            scheduler._load_pending_tasks()

            scheduler._publish(scheduler.reminders[0])

            pending_ids = {item["id"] for item in store.pending_tasks()}
            self.assertIn(task_id, pending_ids)

    def test_wake_frame_buffer_emits_exact_model_frames(self):
        frames = WakeFrameBuffer(frame_size=1280)

        self.assertEqual([], frames.add(np.zeros(512, dtype=np.int16)))
        emitted = frames.add(np.zeros(1024, dtype=np.int16))

        self.assertEqual(1, len(emitted))
        self.assertEqual(1280, emitted[0].size)
        self.assertEqual(256, frames.samples.size)

    def test_lifecycle_is_thread_safe_and_ignores_subscriber_failure(self):
        lifecycle = Lifecycle()
        received = []
        lifecycle.subscribe(lambda event: received.append(event))
        lifecycle.subscribe(lambda event: (_ for _ in ()).throw(RuntimeError("bad")))

        with redirect_stdout(io.StringIO()):
            event = lifecycle.emit("thinking", channel="voice")

        self.assertEqual("thinking", lifecycle.snapshot()["state"])
        self.assertEqual(event["sequence"], received[0]["sequence"])

    def test_memory_store_uses_wal_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.db"
            store = MemoryStore(path)

            with store._connect() as conn:
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

            self.assertEqual("wal", journal_mode)
            self.assertEqual(30000, busy_timeout)
            self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_openrouteservice_health_uses_provider_specific_key(self):
        env = {
            "ENTITY_ROUTES_PROVIDER": "openrouteservice",
            "ENTITY_OPENROUTESERVICE_API_KEY": "test-key",
            "ENTITY_HOME_ADDRESS": "Home",
        }

        with patch.dict(os.environ, env, clear=False):
            issues = StartupHealthCheck()._route_issues()

        self.assertEqual([], issues)

    def test_model_router_does_not_duplicate_partially_streamed_response(self):
        class FailingProvider:
            name = "local_fast"

            def available(self):
                return True

            def stream(self, prompt, temperature=0):
                yield "partial"
                raise ModelUnavailable("connection lost")

        class BackupProvider:
            name = "local_thinking"
            calls = 0

            def available(self):
                return True

            def stream(self, prompt, temperature=0):
                self.calls += 1
                yield "duplicate"

        backup = BackupProvider()
        stream = ModelRouter(
            providers=[FailingProvider(), backup]
        ).stream("test")

        self.assertEqual("partial", next(stream))

        with self.assertRaisesRegex(ModelUnavailable, "streaming began"):
            next(stream)

        self.assertEqual(0, backup.calls)

    def test_calendar_alert_uses_route_duration_instead_of_fixed_lead(self):
        class CalendarClient:
            calendar_id = "primary"

        class Estimate:
            duration_seconds = 45 * 60

        class Routes:
            home_address = "Home"
            buffer_minutes = 10

            def available(self):
                return True

            def estimate(self, origin, destination):
                return Estimate()

        observer = CalendarObserver(
            client=CalendarClient(),
            route_planner=Routes()
        )
        start = datetime.now(observer.timezone) + timedelta(minutes=50)
        payload = {
            "start": start.isoformat(),
            "location": "Destination",
            "event_id": "event"
        }

        self.assertTrue(observer._within_alert_window(payload))

    def test_runtime_event_failure_does_not_leave_queue_unfinished(self):
        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.event_bus = EventBus()
        runtime.lifecycle = Lifecycle()
        runtime.scheduler_observer = None
        failures = []
        runtime.handle_event = lambda event: (_ for _ in ()).throw(
            RuntimeError("synthetic failure")
        )
        runtime._handle_event_error = lambda event, error: failures.append(
            (event.type, str(error))
        )
        runtime.event_bus.publish(Event(source="test", type="test"))

        result = runtime.process_next_event(timeout=0.1)

        self.assertIsNone(result)
        self.assertEqual([("test", "synthetic failure")], failures)
        self.assertEqual(0, runtime.event_bus.queue.unfinished_tasks)

    def test_router_requests_structured_json_from_provider(self):
        class Provider:
            name = "local_fast"
            response_format = None

            def available(self):
                return True

            def generate(self, prompt, temperature=0, response_format=None):
                self.response_format = response_format
                return '{"answer": true}'

        provider = Provider()
        payload = ModelRouter(providers=[provider]).generate_json("test")

        self.assertEqual({"answer": True}, payload)
        self.assertEqual("json", provider.response_format)

    def test_weather_uses_deterministic_fast_path_without_planner(self):
        class Weather:
            def lookup(self, location="", question=""):
                return "Weather result"

        class Store:
            def __init__(self):
                self.decisions = []

            def add_planner_decision(self, **kwargs):
                self.decisions.append(kwargs)
                return "decision"

        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.lifecycle = Lifecycle()
        runtime.arithmetic_handler = ArithmeticHandler()
        runtime.weather_tool = Weather()
        runtime.task_store = Store()

        response = runtime._handle_read_only_fast_path(
            "What is the weather today?"
        )

        self.assertEqual("Weather result", response)
        self.assertEqual(
            "deterministic_weather",
            runtime.task_store.decisions[0]["intent"]
        )

    def test_runtime_acknowledges_reminder_only_after_delivery(self):
        class Store:
            completed = []

            def complete_task(self, task_id):
                self.completed.append(task_id)

        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.task_store = Store()
        runtime._record_event = lambda event: None
        runtime._learn_from_event = lambda event: None
        runtime.handle_reminder = lambda event: event.message
        event = Event(
            source="scheduler",
            type="reminder",
            payload={"message": "test", "task_id": "task"}
        )

        runtime.handle_event(event)

        self.assertEqual(["task"], runtime.task_store.completed)

    def test_runtime_retries_undelivered_reminder(self):
        retries = []
        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime._record_event = lambda event: None
        runtime._learn_from_event = lambda event: None
        runtime.handle_reminder = lambda event: None
        runtime._retry_reminder = lambda event: retries.append(event)
        event = Event(
            source="scheduler",
            type="reminder",
            payload={"message": "test", "task_id": "task"}
        )

        runtime.handle_event(event)

        self.assertEqual([event], retries)


if __name__ == "__main__":
    unittest.main()
