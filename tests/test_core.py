import tempfile
import unittest
from pathlib import Path

from agent.confirmations import ConfirmationStore
from agent.math_tools import ArithmeticHandler
from agent.memory.store import MemoryStore
from agent.models.router import ModelRouter
from agent.planner import AgentPlanner
from agent.weather import WeatherReport


class CoreBehaviorTests(unittest.TestCase):
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

if __name__ == "__main__":
    unittest.main()
