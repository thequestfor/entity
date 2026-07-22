import os
import io
import json
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np

from agent.audio.frames import WakeFrameBuffer
from agent.audio.activity import emit_speech_output_activity
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
from agent.planner import AgentPlan, PlanStep
from agent.research import DuckDuckGoParser
from agent.events import Action, Event
from agent.actuators.speech import SpeechActuator
from agent.runtime import EntityRuntime
from agent.speech.queue import SpeechQueue
from agent.visual.unreal import STATE_PROFILES, UnrealRemoteControlSink
from tts.playback import _speech_levels


class ResilienceTests(unittest.TestCase):
    def test_playback_meter_tracks_speech_envelope(self):
        samplerate = 1000
        silence = np.zeros(200, dtype=np.float32)
        time_axis = np.arange(400, dtype=np.float32) / samplerate
        speech = np.sin(2 * np.pi * 80 * time_axis).astype(np.float32) * 0.4

        levels = _speech_levels(
            np.concatenate([silence, speech]),
            samplerate,
            updates_per_second=20
        )

        self.assertTrue(all(level == 0 for level in levels[:4]))
        self.assertGreater(max(levels[4:]), 0.8)

    def test_speech_activity_listener_is_scoped_to_actuator(self):
        levels = []

        def say(_text):
            emit_speech_output_activity(0.72)

        fake_speech = types.SimpleNamespace(say=say)
        action = Action(type="speak", payload={"text": "Hello"})

        with patch.dict(sys.modules, {"speech": fake_speech}):
            SpeechActuator(on_activity=levels.append).execute(action)

        emit_speech_output_activity(0.25)
        self.assertEqual([0.72], levels)

    def test_speech_actuator_queues_phrase_before_stream_finishes(self):
        calls = []
        waited = []
        fake_speech = types.SimpleNamespace(
            stream_phrase=lambda phrase: calls.append(phrase),
            stream_text=lambda token: calls.append(token),
            flush=lambda: calls.append("flush"),
            wait=lambda: waited.append(True),
            say=lambda text: calls.append(text)
        )

        def phrases():
            yield "First phrase."
            self.assertEqual(["First phrase."], calls)
            yield " Second phrase."

        action = Action(
            type="speak",
            payload={"stream": phrases(), "phrased_stream": True}
        )

        with patch.dict(sys.modules, {"speech": fake_speech}):
            response = SpeechActuator().execute(action)

        self.assertEqual("First phrase. Second phrase.", response)
        self.assertEqual(["First phrase.", " Second phrase."], calls)
        self.assertEqual([True], waited)

    def test_route_question_uses_verified_provider_instead_of_chat(self):
        class Routes:
            home_address = "7600 Stonehaven Dr"

            def travel_time(self, origin, destination):
                return f"verified: {origin} -> {destination}: 12 minutes"

        class Store:
            def get_state(self, key):
                return None

            def set_state(self, key, value):
                raise AssertionError("No pending route should be stored")

            def add_planner_decision(self, **kwargs):
                return kwargs

        class Lifecycle:
            def emit(self, *args, **kwargs):
                return None

        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.route_planner = Routes()
        runtime.task_store = Store()
        runtime.lifecycle = Lifecycle()

        response = runtime._handle_route_time_command(
            "How long is the drive to 5815 Blakeney Park Dr?"
        )

        self.assertIn("verified", response)
        self.assertIn("12 minutes", response)

    def test_route_origin_followup_completes_pending_lookup(self):
        class Routes:
            home_address = ""

            def travel_time(self, origin, destination):
                return f"verified: {origin} -> {destination}"

        class Store:
            state = None

            def get_state(self, key):
                return self.state

            def set_state(self, key, value):
                self.state = value

            def add_planner_decision(self, **kwargs):
                return kwargs

        class Lifecycle:
            def emit(self, *args, **kwargs):
                return None

        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.route_planner = Routes()
        runtime.task_store = Store()
        runtime.lifecycle = Lifecycle()

        question = runtime._handle_route_time_command(
            "How long is the drive to Blakeney Park?"
        )
        response = runtime._handle_route_time_command(
            "I'm starting at 7600 Stonehaven Dr in Marvin"
        )

        self.assertIn("starting from", question)
        self.assertIn("7600 Stonehaven", response)
        self.assertIsNone(runtime.task_store.state)

    def test_route_provider_failure_never_falls_back_to_a_guess(self):
        class Routes:
            home_address = "Home"

            def travel_time(self, origin, destination):
                raise RuntimeError("provider unavailable")

        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.route_planner = Routes()

        response = runtime._verified_route_time("Home", "Clinic")

        self.assertIn("couldn't retrieve a verified route time", response)
        self.assertIn("won't estimate", response)

    def test_route_parser_uses_final_to_as_destination(self):
        runtime = EntityRuntime.__new__(EntityRuntime)

        origin, destination = runtime._route_endpoints(
            "How long does it take to drive to Spectrum Center?"
        )

        self.assertIsNone(origin)
        self.assertEqual("Spectrum Center", destination)

    def test_ordinary_conversation_bypasses_action_planner(self):
        runtime = EntityRuntime.__new__(EntityRuntime)

        self.assertFalse(runtime._should_use_action_planner("How are you?"))
        self.assertFalse(
            runtime._should_use_action_planner(
                "Help me think through tomorrow's visual design session."
            )
        )

    def test_external_action_requests_use_planner(self):
        runtime = EntityRuntime.__new__(EntityRuntime)

        self.assertTrue(
            runtime._should_use_action_planner(
                "Set a reminder and add it to my Calendar."
            )
        )
        self.assertTrue(
            runtime._should_use_action_planner("Send this through ntfy.")
        )

    def test_unsupported_external_actions_are_truthful(self):
        runtime = EntityRuntime.__new__(EntityRuntime)

        calendar = runtime._handle_unsupported_external_action(
            "Delete every event from my Google Calendar."
        )
        email = runtime._handle_unsupported_external_action(
            "Email my professor."
        )
        booking = runtime._handle_unsupported_external_action(
            "Book me a flight."
        )

        self.assertIn("cannot delete", calendar)
        self.assertIn("did not change", calendar)
        self.assertIn("cannot send", email)
        self.assertIn("cannot make purchases", booking)

    def test_recurring_reminder_is_not_silently_reduced_to_one_time(self):
        runtime = EntityRuntime.__new__(EntityRuntime)

        response = runtime._create_reminder_from_args(
            {
                "text": "Take medicine",
                "time": "2099-07-22T08:00:00-04:00",
                "recurrence": "FREQ=DAILY"
            },
            "Every day remind me to take medicine."
        )

        self.assertIn("recurring reminders are not supported", response)

    def test_answer_plan_delegates_to_conversation_without_tool_failure(self):
        class Planner:
            def plan(self, *args, **kwargs):
                return AgentPlan(
                    intent="answer",
                    confidence=1,
                    steps=[PlanStep(tool="answer")]
                )

        class Snapshot:
            def snapshot(self):
                return {}

        class Store:
            update = None

            def recent_planner_decisions(self, limit=5):
                return []

            def add_planner_decision(self, **kwargs):
                return "decision"

            def update_planner_decision(self, decision_id, **kwargs):
                self.update = kwargs

        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.planner = Planner()
        runtime.awareness = Snapshot()
        runtime.presence = Snapshot()
        runtime.task_store = Store()
        runtime.recent_actions = []
        runtime.recent_responses = []
        runtime.actuators = []
        runtime.observers = []

        response = runtime._handle_planned_command("Explain this.")

        self.assertIsNone(response)
        self.assertEqual(
            "delegated_to_conversation",
            runtime.task_store.update["outcome"]
        )

    def test_research_parser_supports_duckduckgo_lite_results(self):
        parser = DuckDuckGoParser(max_results=1)
        parser.feed(
            "<a class='result-link' "
            "href='//duckduckgo.com/l/?uddg=https%3A%2F%2Fnasa.gov%2Fx'>"
            "NASA mission</a>"
            "<td class='result-snippet'>Official mission details.</td>"
        )

        self.assertEqual(1, len(parser.sources))
        self.assertEqual("NASA mission", parser.sources[0].title)
        self.assertEqual("https://nasa.gov/x", parser.sources[0].url)
        self.assertEqual(
            "Official mission details.",
            parser.sources[0].snippet
        )

    def test_structured_calendar_args_bypass_composite_command_reparsing(self):
        runtime = EntityRuntime.__new__(EntityRuntime)
        actions = []
        runtime.execute = lambda action: (
            actions.append(action) or "Calendar event created."
        )
        runtime._notify_significant_action = lambda *args, **kwargs: None

        result = runtime._create_calendar_event_from_args(
            {
                "text": "Wake up",
                "start_time": "2026-07-22T10:00:00-04:00",
                "end_time": "2026-07-22T10:15:00-04:00"
            },
            "Create a reminder, Calendar event, and ntfy alert."
        )

        draft = actions[0].payload["draft"]
        self.assertEqual("Calendar event created.", result)
        self.assertEqual("Wake up", draft.summary)
        self.assertEqual("2026-07-22T10:00:00-04:00", draft.start.isoformat())
        self.assertEqual("2026-07-22T10:15:00-04:00", draft.end.isoformat())

    def test_structured_reminder_args_schedule_exact_time(self):
        class Store:
            task = None

            def add_task(self, **kwargs):
                self.task = kwargs
                return "task-id"

        class Scheduler:
            reminder = None

            def add_reminder_at(self, *args, **kwargs):
                self.reminder = (args, kwargs)

        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.task_store = Store()
        runtime.scheduler_observer = Scheduler()
        runtime._notify_significant_action = lambda *args, **kwargs: None

        result = runtime._create_reminder_from_args(
            {
                "text": "Wake up",
                "time": "2099-07-22T10:00:00-04:00",
                "priority": 9
            },
            "Wake me up",
            source="voice"
        )

        expected = datetime.fromisoformat(
            "2099-07-22T10:00:00-04:00"
        ).timestamp()
        self.assertEqual("Reminder set: Wake up.", result)
        self.assertEqual(expected, runtime.task_store.task["due_at"])
        self.assertEqual(9, runtime.task_store.task["priority"])
        self.assertEqual(expected, runtime.scheduler_observer.reminder[0][0])

    def test_same_time_reminder_covers_scheduled_ntfy(self):
        runtime = EntityRuntime.__new__(EntityRuntime)
        reminder = PlanStep(
            tool="create_reminder",
            args={"time": "2026-07-22T10:00:00-04:00"}
        )
        notify = PlanStep(
            tool="notify",
            args={"time": "2026-07-22T10:00:00-04:00"}
        )

        self.assertTrue(
            runtime._notify_is_covered_by_reminder(
                notify,
                [reminder, notify]
            )
        )

    def test_partial_plan_failure_is_reported_and_recorded(self):
        class Planner:
            def plan(self, *args, **kwargs):
                return AgentPlan(
                    intent="workflow",
                    confidence=1,
                    steps=[
                        PlanStep(tool="create_reminder"),
                        PlanStep(tool="create_calendar_event")
                    ]
                )

        class Snapshot:
            def snapshot(self):
                return {}

        class Store:
            update = None

            def recent_planner_decisions(self, limit=5):
                return []

            def add_planner_decision(self, **kwargs):
                return "decision-id"

            def update_planner_decision(self, decision_id, **kwargs):
                self.update = kwargs

        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.planner = Planner()
        runtime.awareness = Snapshot()
        runtime.presence = Snapshot()
        runtime.task_store = Store()
        runtime.recent_actions = []
        runtime.recent_responses = []
        runtime.actuators = []
        runtime.observers = []
        runtime._plan_needs_confirmation = lambda plan: False
        runtime._notify_significant_plan_step = lambda *args, **kwargs: None
        runtime._execute_plan_step = lambda step, *args, **kwargs: (
            "Reminder set: Wake up."
            if step.tool == "create_reminder"
            else None
        )

        response = runtime._handle_planned_command("workflow")

        self.assertIn("I could not complete: create calendar event.", response)
        self.assertEqual("partially_failed", runtime.task_store.update["outcome"])
        self.assertFalse(
            runtime.task_store.update["metadata"]["step_results"][1]["succeeded"]
        )

    def test_compliance_question_uses_latest_verifiable_workflow(self):
        class Store:
            def recent_planner_decisions(self, limit=20):
                return [
                    {"metadata": {}},
                    {
                        "metadata": {
                            "step_results": [
                                {
                                    "tool": "create_reminder",
                                    "result": "Reminder set.",
                                    "succeeded": True
                                },
                                {
                                    "tool": "create_calendar_event",
                                    "result": None,
                                    "succeeded": False
                                }
                            ]
                        }
                    }
                ]

        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.task_store = Store()

        response = runtime._handle_decision_audit_command(
            "Did you comply with everything I requested?"
        )

        self.assertIn("Completed: create reminder", response)
        self.assertIn("Failed or unverified: create calendar event", response)

    def test_every_entity_visual_state_has_a_distinct_color(self):
        expected_states = {
            "created", "booting", "wake_detected", "listening",
            "transcribing", "thinking", "tool_started", "tool_finished",
            "speaking", "autonomous", "recovering", "service_error",
            "error", "waiting_confirmation", "idle", "stopping", "stopped"
        }

        self.assertEqual(expected_states, set(STATE_PROFILES))
        colors = [STATE_PROFILES[state]["ShellColor"] for state in expected_states]
        self.assertEqual(len(colors), len(set(colors)))

    def test_unreal_visual_sink_sends_remote_control_function_call(self):
        requests = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"{}"

        def open_request(request, timeout):
            requests.append((request, timeout))
            return Response()

        sink = UnrealRemoteControlSink(
            enabled=True,
            base_url="http://127.0.0.1:30010",
            preset="Entity Orb",
            target="function",
            function="Set Entity State",
            parameter="NewState",
            timeout=0.25,
            opener=open_request
        )

        delivered = sink.deliver({"state": "thinking"})

        self.assertTrue(delivered)
        self.assertEqual(1, len(requests))
        request, timeout = requests[0]
        self.assertEqual(
            "http://127.0.0.1:30010/remote/preset/Entity%20Orb/"
            "function/Set%20Entity%20State",
            request.full_url
        )
        self.assertEqual("PUT", request.method)
        self.assertEqual(0.25, timeout)
        self.assertEqual(
            {
                "Parameters": {"NewState": "thinking"},
                "GenerateTransaction": False
            },
            json.loads(request.data)
        )

    def test_unreal_visual_sink_updates_exposed_state_property(self):
        requests = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"{}"

        def open_request(request, timeout):
            requests.append(request)
            return Response()

        sink = UnrealRemoteControlSink(
            enabled=True,
            preset="EntityOrb",
            target="property",
            property_name="EntityState",
            opener=open_request
        )

        self.assertTrue(sink.deliver({"state": "listening"}))
        self.assertEqual(
            "http://127.0.0.1:30010/remote/preset/EntityOrb/"
            "property/EntityState",
            requests[0].full_url
        )
        self.assertEqual(
            {
                "PropertyValue": "listening",
                "GenerateTransaction": False
            },
            json.loads(requests[0].data)
        )

    def test_unreal_visual_sink_maps_state_to_shell_parameters(self):
        requests = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"{}"

        def open_request(request, timeout):
            requests.append(request)
            return Response()

        sink = UnrealRemoteControlSink(
            enabled=True,
            target="component_scalar",
            component_path="/Game/Test.Orb:PersistentLevel.Orb.Shell",
            opener=open_request
        )

        self.assertTrue(sink.deliver({"state": "thinking"}))
        self.assertEqual(4, len(requests))
        payloads = [json.loads(request.data) for request in requests]
        self.assertEqual(
            [
                "ShellStrength",
                "BreathSpeed",
                "BreathExpansion",
                "ShellColor"
            ],
            [item["Parameters"]["ParameterName"] for item in payloads]
        )
        self.assertEqual(
            [28.0, 0.55, 1.05],
            [
                item["Parameters"]["ParameterValue"]
                for item in payloads[:3]
            ]
        )
        self.assertEqual(
            {"X": 0.72, "Y": 0.08, "Z": 1.0},
            payloads[3]["Parameters"]["ParameterValue"]
        )
        self.assertTrue(
            all(
                request.full_url.endswith("/remote/object/call")
                for request in requests
            )
        )

    def test_unreal_visual_sink_does_not_raise_when_unavailable(self):
        def unavailable(request, timeout):
            raise urllib.error.URLError("offline")

        sink = UnrealRemoteControlSink(
            enabled=True,
            opener=unavailable
        )

        with redirect_stdout(io.StringIO()):
            delivered = sink.deliver({"state": "idle"})

        self.assertFalse(delivered)

    def test_unreal_sink_ignores_high_frequency_speech_activity(self):
        sink = UnrealRemoteControlSink(enabled=True)

        sink.publish({"state": "speech_activity", "details": {"activity": 0.8}})

        self.assertTrue(sink._queue.empty())

    def test_runtime_marks_autonomous_work_for_visual_clients(self):
        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.lifecycle = Lifecycle()
        runtime._record_event = lambda event: None
        runtime._learn_from_event = lambda event: None
        runtime.handle_autonomous_goal = lambda event: "done"
        states = []
        runtime.lifecycle.subscribe(lambda event: states.append(event["state"]))
        event = Event(
            source="autonomy",
            type="autonomous_goal",
            payload={"goal": {"name": "periodic_reflection"}}
        )

        self.assertEqual("done", runtime.handle_event(event))
        self.assertEqual(["autonomous", "idle"], states)

    def test_startup_service_issues_emit_visual_error_state(self):
        class Health:
            def alert_message(self):
                return "Service unavailable."

        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.lifecycle = Lifecycle()
        runtime.startup_health = Health()
        runtime._deliver_alert = lambda *args, **kwargs: None
        states = []
        runtime.lifecycle.subscribe(lambda event: states.append(event["state"]))

        runtime._run_startup_health_check()

        self.assertEqual(["service_error"], states)

    def test_runtime_connects_and_disconnects_visual_sink(self):
        class Sink:
            enabled = True

            def __init__(self):
                self.events = []
                self.started = False
                self.closed = False

            def start(self):
                self.started = True

            def publish(self, event):
                self.events.append(event)

            def close(self):
                self.closed = True

        runtime = EntityRuntime.__new__(EntityRuntime)
        runtime.lifecycle = Lifecycle()
        runtime.visual_sink = Sink()

        runtime._start_visual_sink()
        runtime.lifecycle.emit("speaking")
        runtime._stop_visual_sink()
        runtime.lifecycle.emit("idle")

        self.assertTrue(runtime.visual_sink.started)
        self.assertTrue(runtime.visual_sink.closed)
        self.assertEqual(
            ["speaking"],
            [event["state"] for event in runtime.visual_sink.events]
        )

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

    def test_explicit_read_about_online_request_uses_research(self):
        runtime = EntityRuntime.__new__(EntityRuntime)

        query = runtime._research_query(
            "Read about Shakespeare online and report back to me."
        )

        self.assertEqual("Shakespeare", query)

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
