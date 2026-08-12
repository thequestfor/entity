import json
import tempfile
import unittest
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from agent.connectors.news import NewsFeedConnector
from agent.intelligence.article_acquisition import ArticleAcquisitionEngine
from agent.intelligence.config import IntelligenceConfig
from agent.intelligence.models import SourceItem
from agent.intelligence.store import IntelligenceStore
from agent.intelligence.workload import WorkloadMonitor
from agent.intelligence.web import IntelligenceDashboard


class WorkloadHealthTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "intelligence.db"
        self.store = IntelligenceStore(self.path)
        self.store.configure_workload_limits(
            "article-acquisition", 25, 100, 2, 10
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_storage_boundaries_sum_database_family_and_deduplicate_state(self):
        sizes = {self.path.name: 80, self.path.name + "-wal": 15,
                 self.path.name + "-shm": 5}
        monitor = WorkloadMonitor(
            self.store, disk_soft_limit_bytes=100,
            disk_hard_limit_bytes=200,
            size_reader=lambda path: sizes[path.name],
            free_reader=lambda _path: 500,
            clock=lambda: datetime(2026, 8, 11, 12, tzinfo=UTC),
        )
        self.assertEqual("disk-soft-limit", monitor.refresh()["status"])
        self.assertEqual("disk-soft-limit", monitor.refresh()["status"])
        health = self.store.workload_health()
        self.assertEqual(100, health["storage"]["combined_bytes"])
        self.assertEqual(1, len(health["transitions"]))

        sizes[self.path.name] = 180
        self.assertEqual("disk-hard-limit", monitor.refresh()["status"])
        self.assertEqual(2, len(self.store.workload_health()["transitions"]))

    def test_missing_sidecars_are_zero_but_unreadable_database_is_unknown(self):
        def reader(path):
            if path == self.path:
                raise OSError("unreadable")
            raise FileNotFoundError

        monitor = WorkloadMonitor(
            self.store, size_reader=reader, free_reader=lambda _path: 100
        )
        self.assertEqual("unknown", monitor.refresh()["status"])
        storage = self.store.workload_health()["storage"]
        self.assertIsNone(storage["database_bytes"])
        self.assertEqual(0, storage["wal_bytes"])
        self.assertEqual(0, storage["shm_bytes"])

    def test_invalid_disk_limit_configuration_uses_safe_defaults(self):
        with patch.dict("os.environ", {
            "ENTITY_INTELLIGENCE_DISK_SOFT_LIMIT_BYTES": "300",
            "ENTITY_INTELLIGENCE_DISK_HARD_LIMIT_BYTES": "200",
        }):
            config = IntelligenceConfig.from_env()
        self.assertEqual(2_147_483_648,
                         config.intelligence_disk_soft_limit_bytes)
        self.assertEqual(3_221_225_472,
                         config.intelligence_disk_hard_limit_bytes)

    def test_soft_behavior_processes_fresh_and_leaves_historical_unqueued(self):
        connector = NewsFeedConnector(
            "Workload Fixture", "https://workload.test/feed",
            article_acquisition_mode="publisher-page",
            article_hosts=("workload.test",),
        )
        self.store.register_source(
            connector.source_id, connector.name, connector.kind,
            base_url=connector.base_url, poll_seconds=connector.poll_seconds,
        )
        self.store.register_source_policy(
            connector.source_id, connector.source_policy
        )
        self.store.ingest_items(connector.source_id, [
            SourceItem("old", "Old", "https://workload.test/old",
                       summary="old", category="traditional-news"),
            SourceItem("fresh", "Fresh", "https://workload.test/fresh",
                       summary="fresh", category="traditional-news"),
        ])
        with self.store._connect() as connection:
            connection.execute(
                "UPDATE documents SET retrieved_at='2020-01-01T00:00:00Z' "
                "WHERE external_id='old'"
            )

        class SoftMonitor:
            def allowed_work_classes(self):
                return ("fresh",)

        calls = []
        result = ArticleAcquisitionEngine(
            self.store, enabled=True, workload_monitor=SoftMonitor(),
            fetch_html=lambda url, *_args: (
                calls.append(url) or {"status": 200, "final_url": url,
                "headers": {}, "body": "<article>" + ("word " * 220)
                + "</article>"}
            ),
        ).run_batch()
        self.assertEqual(1, result["processed"])
        self.assertEqual(["https://workload.test/fresh"], calls)
        with self.store._connect() as connection:
            tasks = connection.execute(
                "SELECT work_class,status FROM article_acquisition_tasks"
            ).fetchall()
        self.assertEqual([("fresh", "complete")], [tuple(row) for row in tasks])

    def test_hard_behavior_does_not_mutate_or_fetch_queued_tasks(self):
        class HardMonitor:
            def allowed_work_classes(self):
                return ()

        before = json.dumps(self.store.article_analysis_overview()["tasks"])
        called = []
        result = ArticleAcquisitionEngine(
            self.store, enabled=True, workload_monitor=HardMonitor(),
            fetch_html=lambda *_args: called.append(True),
        ).run_batch()
        after = json.dumps(self.store.article_analysis_overview()["tasks"])
        self.assertEqual("disk-hard-limit", result["shed"])
        self.assertEqual(before, after)
        self.assertEqual([], called)

    def test_workload_api_is_bounded_and_exposes_no_private_path(self):
        WorkloadMonitor(self.store).refresh()
        static = Path(self.temporary.name) / "dashboard"
        static.mkdir()
        (static / "index.html").write_text("ok", encoding="utf-8")
        dashboard = IntelligenceDashboard(
            self.store, host="127.0.0.1", port=0, static_root=static
        )
        try:
            dashboard.start()
            with urllib.request.urlopen(
                dashboard.url
                + "api/intelligence/workload-health?window_minutes=99999"
                + "&transition_limit=99999", timeout=2
            ) as response:
                payload = json.loads(response.read())
        finally:
            dashboard.stop()
        encoded = json.dumps(payload)
        self.assertEqual(1440, payload["recent"]["window_minutes"])
        self.assertNotIn(str(self.path), encoded)
        self.assertNotIn("normalized_text", encoded)


if __name__ == "__main__":
    unittest.main()
