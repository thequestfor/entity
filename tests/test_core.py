import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.confirmations import ConfirmationStore
from agent.brain.brain import Brain
from agent.brain.prompts import entity_prompt
from agent.briefing import TodayBriefing
from agent.math_tools import ArithmeticHandler
from agent.memory.store import MemoryStore
from agent.memory.research import ResearchMemoryIngestor
from agent.models.router import ModelRouter
from agent.models.base import ModelUnavailable
from agent.planner import AgentPlan, AgentPlanner, PlanStep
from agent.runtime import EntityRuntime
from agent.goals import AutonomousGoalPolicy
from agent.knowledge import LearningDigest, WorldviewDigest
from agent.location import LocationResolver
from agent.weather import WeatherReport, WeatherTool
from agent.speech.buffer import SentenceBuffer


class CoreBehaviorTests(unittest.TestCase):
    def test_sentence_buffer_releases_long_natural_phrase(self):
        buffer = SentenceBuffer(soft_limit=40, hard_limit=70)

        phrases = buffer.add(
            "This is a deliberately long opening phrase, followed by more text"
        )

        self.assertEqual(
            ["This is a deliberately long opening phrase,"],
            phrases
        )
        self.assertEqual(["followed by more text"], buffer.flush())

    def test_brain_releases_first_sentence_before_model_finishes(self):
        class Memory:
            remembered = None

            def context_for(self, command):
                return {}

            def remember(self, category, item):
                self.remembered = item

        progress = []

        def live_stream(*args, **kwargs):
            progress.append("first")
            yield "The first sentence is ready."
            progress.append("second")
            yield " The second sentence follows."

        memory = Memory()
        response = Brain(
            memory=memory,
            stream_generator=live_stream
        ).respond_stream("Hello", state={})

        self.assertEqual("The first sentence is ready.", next(response))
        self.assertEqual(["first"], progress)
        self.assertEqual(" The second sentence follows.", next(response))

        with self.assertRaises(StopIteration):
            next(response)

        self.assertEqual(["first", "second"], progress)
        self.assertEqual(
            "The first sentence is ready. The second sentence follows.",
            memory.remembered["entity"]
        )

    def test_brain_holds_contaminated_opening_until_rewritten(self):
        class Memory:
            remembered = None

            def context_for(self, command):
                return {}

            def remember(self, category, item):
                self.remembered = item

        memory = Memory()
        brain = Brain(
            memory=memory,
            generator=lambda *args, **kwargs: "The verified answer is concise.",
            stream_generator=lambda *args, **kwargs: iter([
                "AFFIRMATIVE, BEN. SYSTEM OPERATIONAL."
            ])
        )

        response = "".join(brain.respond_stream("Question", state={}))

        self.assertEqual("The verified answer is concise.", response)
        self.assertEqual(response, memory.remembered["entity"])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.temp_dir.name) / "memory.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_memory_store_searches_indexed_content(self):
        self.store.add_memory(
            kind="preference",
            content="Ben prefers concise status reports",
            source="user",
            importance=7,
        )

        results = self.store.search("concise reports")

        self.assertEqual(1, len(results))
        self.assertEqual("preference", results[0]["kind"])

    def test_memory_store_deduplicates_identical_reflections(self):
        first = self.store.add_memory(
            "reflection",
            "Review this failure once.",
            source="autonomy"
        )
        second = self.store.add_memory(
            "reflection",
            "Review this failure once.",
            source="autonomy"
        )

        self.assertEqual(first, second)
        self.assertEqual(1, self.store.count_memories(kind="reflection"))

    def test_research_memory_deduplicates_close_paraphrases(self):
        self.store.add_memory(
            "web_fact",
            (
                "The Unreal Remote Control API is disabled by default in "
                "packaged projects or when running with the game flag."
            ),
            source="research"
        )
        ingestor = ResearchMemoryIngestor.__new__(ResearchMemoryIngestor)
        ingestor.store = self.store

        duplicate = ingestor._has_duplicate_memory(
            (
                "The Unreal Remote Control API is disabled by default in "
                "packaged projects and when running with the game flag."
            ),
            "web_fact"
        )

        self.assertTrue(duplicate)

    def test_autonomy_does_not_review_same_failed_decision_repeatedly(self):
        policy = AutonomousGoalPolicy.__new__(AutonomousGoalPolicy)
        decisions = [
            {
                "id": "decision",
                "outcome": "failed",
                "updated_at": "2026-07-21T10:00:00Z"
            }
        ]
        goals = [
            {
                "name": "review_failed_tool",
                "created_at": "2026-07-21T10:01:00Z"
            }
        ]

        self.assertIsNone(policy._recent_failed_decision(decisions, goals))

    def test_confirmation_store_expires_pending_plan(self):
        class Plan:
            intent = "test"
            confidence = 1.0
            response = ""
            reason = ""
            steps = []

        confirmations = ConfirmationStore(store=self.store, ttl_seconds=-1)
        confirmations.create(Plan(), "test")

        self.assertIsNone(confirmations.current())

    def test_router_extracts_json_from_markdown_fence(self):
        payload = ModelRouter(providers=[])._parse_json(
            '```json\n{"intent": "answer", "confidence": 1}\n```'
        )

        self.assertEqual("answer", payload["intent"])

    def test_router_keeps_simple_why_questions_on_fast_path(self):
        router = ModelRouter(providers=[])

        self.assertFalse(router.should_escalate("Why do rainbows form?"))
        self.assertFalse(router.should_escalate("What do you think?"))
        self.assertTrue(
            router.should_escalate(
                "Think carefully through this scheduling conflict."
            )
        )

    def test_router_prefers_cloud_while_unreal_is_reachable(self):
        class Provider:
            def __init__(self, name):
                self.name = name

            def available(self):
                return True

        router = ModelRouter(
            providers=[Provider("local_fast"), Provider("cloud_openai")],
            unreal_probe=lambda: True
        )

        with patch.dict(
            "os.environ",
            {
                "ENTITY_PREFER_CLOUD_WHEN_UNREAL": "true",
                "ENTITY_UNREAL_ENABLED": "true"
            }
        ):
            providers = list(router._providers_for("hello", None, "auto"))

        self.assertEqual(
            ["cloud_openai", "local_fast"],
            [provider.name for provider in providers]
        )

    def test_router_keeps_local_first_when_unreal_is_unavailable(self):
        class Provider:
            def __init__(self, name):
                self.name = name

            def available(self):
                return True

        router = ModelRouter(
            providers=[Provider("local_fast"), Provider("cloud_openai")],
            unreal_probe=lambda: False
        )

        with patch.dict(
            "os.environ",
            {
                "ENTITY_PREFER_CLOUD_WHEN_UNREAL": "true",
                "ENTITY_UNREAL_ENABLED": "true"
            }
        ):
            providers = list(router._providers_for("hello", None, "auto"))

        self.assertEqual(
            ["local_fast", "cloud_openai"],
            [provider.name for provider in providers]
        )

    def test_router_uses_thinking_model_first_for_worldview_synthesis(self):
        class Provider:
            def __init__(self, name):
                self.name = name

            def available(self):
                return True

        router = ModelRouter(providers=[
            Provider("local_fast"),
            Provider("local_thinking"),
            Provider("cloud_openai")
        ])

        providers = list(router._providers_for(
            "world event", None, "world_understanding"
        ))

        self.assertEqual(
            ["local_thinking", "cloud_openai", "local_fast"],
            [provider.name for provider in providers]
        )

    def test_planner_rejects_unknown_tools(self):
        planner = AgentPlanner.__new__(AgentPlanner)

        plan = planner._validated(
            {
                "intent": "unsafe",
                "confidence": 1,
                "steps": [{"tool": "shell", "args": {}}],
            }
        )

        self.assertIsNone(plan)

    def test_planner_never_requires_confirmation_to_ask_a_question(self):
        planner = AgentPlanner.__new__(AgentPlanner)

        plan = planner._validated(
            {
                "intent": "clarify",
                "confidence": 1,
                "steps": [
                    {
                        "tool": "ask",
                        "args": {"question": "What time?"},
                        "requires_confirmation": True
                    }
                ]
            }
        )

        self.assertFalse(plan.steps[0].requires_confirmation)

    def test_planner_does_not_expose_its_draft_as_the_answer(self):
        planner = AgentPlanner.__new__(AgentPlanner)

        plan = planner._validated(
            {
                "intent": "factual_answer",
                "confidence": 1,
                "response": "SYSTEM OPERATIONAL. PROCESSING.",
                "steps": [
                    {
                        "tool": "answer",
                        "args": {"text": "SYSTEM OPERATIONAL. PROCESSING."}
                    }
                ]
            }
        )

        self.assertEqual({}, plan.steps[0].args)
        self.assertEqual("", plan.response)

    def test_planner_preserves_explicit_calendar_reminder_and_ntfy(self):
        planner = AgentPlanner.__new__(AgentPlanner)
        plan = AgentPlan(
            intent="create_reminder",
            confidence=1,
            steps=[
                PlanStep(
                    tool="create_reminder",
                    args={
                        "text": "Wake up",
                        "time": "2026-07-22T10:00:00-04:00"
                    }
                )
            ]
        )

        result = planner._ensure_explicit_tools(
            plan,
            "Set a reminder, add it to Google Calendar, and use ntfy."
        )

        self.assertEqual(
            ["create_reminder", "create_calendar_event", "notify"],
            [step.tool for step in result.steps]
        )
        self.assertEqual(
            "2026-07-22T10:00:00-04:00",
            result.steps[1].args["start_time"]
        )

    def test_planner_enriches_explicit_calendar_step_with_shared_time(self):
        planner = AgentPlanner.__new__(AgentPlanner)
        plan = AgentPlan(
            intent="wake_workflow",
            confidence=1,
            steps=[
                PlanStep(
                    tool="create_reminder",
                    args={
                        "text": "Wake up",
                        "time": "2026-07-22T10:00:00-04:00"
                    }
                ),
                PlanStep(
                    tool="create_calendar_event",
                    args={"text": "Wake up"}
                )
            ]
        )

        result = planner._ensure_explicit_tools(
            plan,
            "Add a reminder to my Calendar."
        )

        self.assertEqual(
            "2026-07-22T10:00:00-04:00",
            result.steps[1].args["start_time"]
        )

    def test_planner_defers_briefing_in_wake_workflow(self):
        planner = AgentPlanner.__new__(AgentPlanner)
        plan = AgentPlan(
            intent="wake_and_brief",
            confidence=1,
            steps=[
                PlanStep(
                    tool="create_reminder",
                    args={
                        "text": "Wake up",
                        "time": "2026-07-23T06:00:00-04:00"
                    }
                ),
                PlanStep(tool="briefing")
            ]
        )

        result = planner._ensure_explicit_tools(
            plan,
            "Wake me at 6 AM tomorrow and deliver the daily briefing."
        )

        self.assertEqual(["schedule_briefing"], [
            step.tool for step in result.steps
        ])
        self.assertEqual(
            "2026-07-23T06:00:00-04:00",
            result.steps[0].args["time"]
        )

    def test_memory_context_includes_recent_runtime_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / "context.db")
            from agent.events import Event
            store.add_event(Event(
                source="intelligence",
                type="intelligence_update",
                payload={"message": "Integrated two new reports."}
            ))

            context = store.recall_context("reports")

            self.assertEqual(
                "intelligence_update",
                context["recent_observations"][0]["type"]
            )

    def test_planner_combines_separate_calendar_date_and_time(self):
        planner = AgentPlanner.__new__(AgentPlanner)
        steps = [
            PlanStep(
                tool="create_calendar_event",
                args={"date": "2026-07-23", "time": "09:30:00"}
            )
        ]

        self.assertEqual(
            "2026-07-23T09:30:00",
            planner._planned_time(steps)
        )

    def test_brain_rewrites_internal_status_report_before_speaking(self):
        class Memory:
            remembered = None

            def context_for(self, command):
                return {}

            def remember(self, category, item):
                self.remembered = item

        drafts = iter(
            [
                "AFFIRMATIVE, BEN. SYSTEM OPERATIONAL. PROCESSING.",
                "Shakespeare was born in Stratford-upon-Avon, England."
            ]
        )
        memory = Memory()
        brain = Brain(
            memory=memory,
            generator=lambda *args, **kwargs: next(drafts)
        )

        response = "".join(
            brain.respond_stream(
                "Where was Shakespeare born?",
                state={}
            )
        )

        self.assertEqual(
            "Shakespeare was born in Stratford-upon-Avon, England.",
            response
        )
        self.assertEqual(response, memory.remembered["entity"])

    def test_brain_reports_model_outage_without_crashing(self):
        class Memory:
            def context_for(self, command):
                return {}

            def remember(self, category, item):
                pass

        def unavailable(*args, **kwargs):
            raise ModelUnavailable("offline")

        response = "".join(
            Brain(memory=Memory(), generator=unavailable).respond_stream(
                "Hello?",
                state={}
            )
        )

        self.assertIn("I do not have an available language model", response)

    def test_entity_prompt_rejects_fake_operations_narration(self):
        prompt = entity_prompt("identity", {}, {}, "Where was Shakespeare born?")

        self.assertIn("Answer the user's question directly", prompt)
        self.assertIn("Never output internal workflow narration", prompt)

    def test_entity_prompt_omits_contaminated_prior_response(self):
        prompt = entity_prompt(
            "identity",
            {
                "relevant_memories": [],
                "recent_conversations": [
                    {
                        "user_text": "Where?",
                        "entity_text": "SYSTEM OPERATIONAL. MEMORY INTEGRITY VERIFIED."
                    }
                ]
            },
            {},
            "Where was Shakespeare born?"
        )

        self.assertNotIn("MEMORY INTEGRITY VERIFIED", prompt)
        self.assertIn("omitted because it exposed internal narration", prompt)

    def test_arithmetic_handler_uses_safe_expression_subset(self):
        handler = ArithmeticHandler()

        self.assertEqual("2 + 3 * 4 = 14.", handler.answer("What is 2 + 3 * 4?"))
        self.assertIsNone(handler.answer("Run __import__('os').system('id')"))

    def test_weather_report_adds_question_specific_advice(self):
        report = WeatherReport(
            location="Charlotte",
            temperature_f=50,
            apparent_temperature_f=48,
            precipitation_probability=70,
            condition="Rain",
        )

        response = report.format_response("Do I need an umbrella and jacket?")

        self.assertIn("Bring an umbrella", response)
        self.assertIn("light jacket", response)

    def test_weather_resolver_prefers_qualified_exact_location(self):
        tool = WeatherTool.__new__(WeatherTool)
        results = [
            {
                "name": "Marvin", "admin1": "South Dakota",
                "country": "United States", "population": 33
            },
            {
                "name": "Marvin", "admin1": "North Carolina",
                "country": "United States", "population": 6181
            }
        ]

        result = tool._best_location(results, "Marvin, North Carolina")

        self.assertEqual("North Carolina", result["admin1"])

    def test_weather_report_includes_rain_uv_wind_and_outfit_advice(self):
        report = WeatherReport(
            location="Marvin, North Carolina, United States",
            temperature_f=79,
            apparent_temperature_f=82,
            precipitation_probability=65,
            wind_speed_mph=10,
            wind_gust_mph=32,
            high_f=89,
            low_f=68,
            apparent_high_f=94,
            apparent_low_f=68,
            uv_index=8,
            precipitation_window="Rain is most likely between 2 PM and 5 PM"
        )

        response = report.format_response("What should I wear today?")

        self.assertIn("Gusts may reach 32 mph", response)
        self.assertIn("Rain is most likely between 2 PM and 5 PM", response)
        self.assertIn("light, breathable clothing", response)
        self.assertIn("sunscreen", response)
        self.assertIn("wind-resistant", response)

    def test_today_briefing_combines_weather_schedule_and_world_model(self):
        class Calendar:
            def ready_for_background_reads(self):
                return False

        class Weather:
            def available(self):
                return True

            def lookup(self, location="", question=""):
                return "Weather for Marvin: clear and 72 degrees."

        class Intelligence:
            def latest_briefing(self):
                return {"content": {
                    "headline": "Two situations changed.",
                    "situations": [{
                        "title": "Regional update", "source_count": 2
                    }]
                }}

        briefing = TodayBriefing(
            calendar_client=Calendar(),
            route_planner=object(),
            store=self.store,
            weather_tool=Weather(),
            intelligence_store=Intelligence()
        ).build()

        self.assertIn("Weather for Marvin", briefing)
        self.assertIn("World intelligence: Two situations changed", briefing)
        self.assertIn("Leading updates: Regional update", briefing)

    def test_learning_digest_reports_retained_memory_and_corroboration(self):
        self.store.add_memory(
            "preference", "Ben prefers concise briefings.",
            source="user", importance=8
        )

        class Intelligence:
            def list_situations(self, limit=100):
                return [{
                    "title": "Example event",
                    "summary": "",
                    "confidence": 0.82,
                    "source_count": 2,
                    "status": "active"
                }]

            def list_documents(self, limit=200):
                return []

        digest = LearningDigest(
            memory_store=self.store,
            intelligence_store=Intelligence()
        ).build()

        self.assertIn("Ben prefers concise briefings", digest)
        self.assertIn("Example event", digest)
        self.assertIn("evidence-weighted and provisional", digest)

    def test_worldview_digest_reports_conclusions_with_uncertainty(self):
        class Intelligence:
            def list_situations(self, limit=100):
                return [
                    {
                        "id": "contested",
                        "title": "Regional escalation",
                        "worldview": "Conditions are worsening.",
                        "worldview_confidence": 0.78,
                        "source_count": 3,
                        "status": "contested",
                        "updated_at": "2026-07-23T10:00:00Z"
                    },
                    {
                        "id": "single-source",
                        "title": "Unverified report",
                        "worldview": "A disruption may be developing.",
                        "worldview_confidence": 0.65,
                        "source_count": 1,
                        "status": "active",
                        "updated_at": "2026-07-23T11:00:00Z"
                    }
                ]

            def worldview_syntheses(self, situation_id, limit=1):
                if situation_id == "contested":
                    return [{
                        "contradictions": [
                            "Sources disagree about the scale of the escalation"
                        ],
                        "open_questions": []
                    }]
                return []

        digest = WorldviewDigest(Intelligence()).build()

        self.assertIn("Regional escalation", digest)
        self.assertIn("Conditions are worsening", digest)
        self.assertIn("Important disagreement", digest)
        self.assertIn("provisional", digest)
        self.assertIn("not private model reasoning", digest)

    def test_worldview_command_is_recognized_before_generic_chat(self):
        runtime = EntityRuntime.__new__(EntityRuntime)

        self.assertTrue(runtime._is_worldview_command(
            "What do you think about the intelligence you've gathered lately?"
        ))

    def test_location_resolver_matches_active_wifi_locally(self):
        with patch.dict(os.environ, {
            "ENTITY_LOCATION_WIFI_MAP": (
                "Home WiFi|Marvin, North Carolina|34.99182|-80.81479"
            ),
            "ENTITY_LOCATION_PUBLIC_IP_ENABLED": "false"
        }, clear=False):
            resolver = LocationResolver(connection_name="Home WiFi")

        estimate = resolver.resolve()

        self.assertEqual("Marvin, North Carolina", estimate.label)
        self.assertEqual("recognized_wifi", estimate.method)
        self.assertIn("No nearby Wi-Fi identifiers were uploaded", resolver.describe())

if __name__ == "__main__":
    unittest.main()
