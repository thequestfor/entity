import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from agent.intelligence.models import SourceItem
from agent.intelligence.replay import (
    ReplayBundle, ReplayError, ReplayRunner, bundle_from_database,
)
from agent.intelligence.source_registry import SourcePolicy
from agent.intelligence.store import IntelligenceStore


FIXTURES = Path(__file__).parent / "fixtures" / "intelligence_replay"


class IntelligenceReplayTests(unittest.TestCase):
    def test_repeated_runs_have_identical_manifest_and_result(self):
        runner = ReplayRunner(batch_size=20)
        first = runner.run_fixture(FIXTURES / "publisher_imbalance.json")
        second = runner.run_fixture(FIXTURES / "publisher_imbalance.json")
        self.assertEqual(first.manifest, second.manifest)
        self.assertEqual(first.summary, second.summary)
        self.assertEqual(1, first.summary["counts"]["events"])
        self.assertEqual(5, first.summary["counts"]["memberships"])
        self.assertEqual(3, first.summary["counts"]["framing_assessments"])
        self.assertEqual(1, first.summary["counts"]["comparisons"])

    def test_event_readiness_pressure_is_deterministic_and_independent(self):
        runner = ReplayRunner(batch_size=2)
        first = runner.run_fixture(FIXTURES / "event_readiness_pressure.json")
        second = runner.run_fixture(FIXTURES / "event_readiness_pressure.json")
        self.assertEqual(first.manifest, second.manifest)
        self.assertEqual(first.summary, second.summary)
        self.assertEqual(7, first.summary["counts"]["documents"])
        self.assertEqual(2, first.summary["counts"]["framing_assessments"])
        self.assertEqual(1, first.summary["counts"]["comparisons"])

    def test_initial_fixture_corpus_reproduces_structural_expectations(self):
        runner = ReplayRunner(batch_size=20)
        results = {
            key: runner.run_fixture(FIXTURES / f"{key}.json").summary
            for key in (
                "publisher_imbalance", "source_outage", "correction",
                "syndication", "duplicate_evidence", "no_event",
            )
        }
        self.assertEqual(1, results["source_outage"]["counts"]["documents"])
        self.assertEqual("unknown-coverage",
                         results["source_outage"]["expected_gaps"][0]["status"])
        self.assertEqual(2, results["correction"]["counts"]["document_versions"])
        self.assertEqual(
            [{"reporting_family_key": "wire-family-1", "count": 2}],
            results["syndication"]["reporting_families"],
        )
        self.assertEqual(1, results["duplicate_evidence"]["counts"]["documents"])
        self.assertEqual(1, results["duplicate_evidence"]["counts"]["document_versions"])
        self.assertEqual(0, results["no_event"]["counts"]["events"])
        self.assertEqual(0, results["no_event"]["counts"]["comparisons"])

    def test_cutoff_excludes_future_correction(self):
        data = json.loads((FIXTURES / "correction.json").read_text())
        data["cutoff"] = "2026-01-03T00:30:00Z"
        result = ReplayRunner().run(ReplayBundle.validate(data))
        self.assertEqual(1, result.summary["counts"]["document_versions"])
        self.assertNotIn("Correction", json.dumps(result.summary))

    def test_total_order_breaks_equal_timestamp_ties(self):
        data = json.loads((FIXTURES / "publisher_imbalance.json").read_text())
        data["documents"] = [data["documents"][3], data["documents"][0]]
        data["documents"][0]["captured_at"] = "2026-01-01T00:01:00Z"
        ordered = ReplayBundle.validate(data).ordered_documents
        self.assertEqual(["replay_a", "replay_b"],
                         [item["source_id"] for item in ordered])

    def test_bundle_validation_fails_closed(self):
        base = json.loads((FIXTURES / "publisher_imbalance.json").read_text())
        cases = []
        unknown = copy.deepcopy(base); unknown["unexpected"] = True
        cases.append((unknown, "bundle-unknown-field"))
        policy = copy.deepcopy(base)
        policy["sources"][0]["policy"]["policy_version"] = "future"
        cases.append((policy, "policy-version-mismatch"))
        bad_hash = copy.deepcopy(base)
        bad_hash["captures"][0]["content_hash"] = "0" * 64
        cases.append((bad_hash, "capture-hash-mismatch"))
        response = copy.deepcopy(base)
        response["frozen_responses"][0]["version"] = "future"
        cases.append((response, "algorithm-version-mismatch"))
        missing = copy.deepcopy(base)
        missing["captures"][0]["normalized_text"] += " changed"
        missing["captures"][0].pop("content_hash")
        cases.append((missing, "frozen-response-missing"))
        for payload, code in cases:
            with self.subTest(code=code), self.assertRaises(ReplayError) as raised:
                ReplayBundle.validate(payload)
            self.assertEqual(code, raised.exception.code)

    def test_manifest_excludes_article_text_and_private_paths(self):
        data = json.loads((FIXTURES / "publisher_imbalance.json").read_text())
        data["captures"][0]["normalized_text"] += " PRIVATE_REPLAY_MARKER"
        data["captures"][0].pop("content_hash")
        text = data["captures"][0]["normalized_text"]
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        for capture in data["captures"]:
            if capture["external_id"] == "a1":
                capture["content_hash"] = content_hash
        data["frozen_responses"].append({
            "method": "semantic-framing-v2", "version": "semantic-framing-v2",
            "content_hash": content_hash, "response": {"observations": []},
        })
        result = ReplayRunner().run(ReplayBundle.validate(data))
        encoded = json.dumps({"manifest": result.manifest,
                              "summary": result.summary})
        self.assertNotIn("PRIVATE_REPLAY_MARKER", encoded)
        self.assertNotIn(str(Path.home()), encoded)
        self.assertNotIn("normalized_text", encoded)

    def test_database_export_is_read_only_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.db"
            store = IntelligenceStore(path)
            store.register_source("fixture", "Fixture", "traditional_news")
            store.register_source_policy("fixture", SourcePolicy(
                "public", "journalistic", "report", "fixture-family",
                ("fixture.test",),
            ))
            store.ingest_replay_item("fixture", SourceItem(
                "one", "Fixture report", "https://fixture.test/one",
                summary="Synthetic report", category="news",
                metadata={"domain": "fixture.test"},
            ), "2026-01-01T00:00:00Z")
            before = path.read_bytes()
            bundle = bundle_from_database(
                path, "2026-01-01T01:00:00Z", ["fixture"], max_items=10
            )
            ReplayRunner().run(bundle)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(1, len(bundle.ordered_documents))

    def test_output_path_guards_and_retained_artifacts(self):
        runner = ReplayRunner()
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "existing"
            existing.mkdir()
            with self.assertRaises(ReplayError) as raised:
                runner.run_fixture(FIXTURES / "no_event.json", existing)
            self.assertEqual("output-exists", raised.exception.code)
            output = Path(directory) / "retained"
            result = runner.run_fixture(FIXTURES / "no_event.json", output)
            self.assertTrue((output / "manifest.json").is_file())
            self.assertTrue((output / "summary.json").is_file())
            self.assertEqual(str(output.resolve()), result.output_directory)

    def test_production_document_ids_remain_nondeterministic(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            ids = []
            for directory in (first_dir, second_dir):
                store = IntelligenceStore(Path(directory) / "db.sqlite")
                store.register_source("fixture", "Fixture", "test")
                store.ingest_items("fixture", [SourceItem(
                    "same", "Same", "https://fixture.test/same"
                )])
                ids.append(store.list_documents()[0]["id"])
            self.assertNotEqual(ids[0], ids[1])


if __name__ == "__main__":
    unittest.main()
