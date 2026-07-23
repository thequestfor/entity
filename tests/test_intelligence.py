import json
import base64
import tempfile
import unittest
import urllib.request
from pathlib import Path

from agent.connectors.cisa import CisaKevConnector
from agent.connectors.eonet import EonetConnector
from agent.connectors.firms import FirmsConnector
from agent.connectors.fred import FredConnector
from agent.connectors.gdacs import GdacsConnector
from agent.connectors.gdelt import GdeltConnector
from agent.connectors.gmail import GmailConnector
from agent.connectors.github_advisories import GitHubAdvisoriesConnector
from agent.connectors.mail_common import secure_write
from agent.connectors.nws import NwsAlertsConnector
from agent.connectors.noaa_swpc import NoaaSpaceWeatherConnector
from agent.connectors.news import NewsFeedConnector
from agent.connectors.outlook import OutlookConnector
from agent.connectors.polymarket import PolymarketConnector
from agent.connectors.reliefweb import ReliefWebConnector
from agent.connectors.telegram import TelegramConnector
from agent.connectors.usgs import UsgsConnector
from agent.connectors.who import WhoOutbreakConnector
from agent.connectors.world_bank import WorldBankIndicatorsConnector
from agent.connectors.x import XConnector
from agent.intelligence.config import IntelligenceConfig
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.reputation import ReputationEngine
from agent.intelligence.service import IntelligenceService
from agent.intelligence.store import IntelligenceStore, canonicalize_url
from agent.intelligence.understanding import UnderstandingEngine
from agent.intelligence.forecasting import ForecastEngine
from agent.intelligence.web import IntelligenceDashboard
from agent.intelligence.worker import IntelligenceWorker


class IntelligenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "intelligence.db"
        self.store = IntelligenceStore(self.path)
        self.store.register_source(
            "fixture",
            "Fixture source",
            "test",
            base_url="https://example.test",
            poll_seconds=60
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_store_applies_versioned_migration_and_private_permissions(self):
        with self.store._connect() as connection:
            version = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
            journal = connection.execute("PRAGMA journal_mode").fetchone()[0]

        self.assertEqual(5, version)
        self.assertEqual("wal", journal.lower())
        self.assertEqual(0o600, self.path.stat().st_mode & 0o777)

    def test_ingest_deduplicates_and_versions_changed_documents(self):
        first = SourceItem(
            external_id="one",
            title="Developing event",
            url="https://example.test/story?utm_source=test&id=1",
            summary="Initial report",
            published_at="2026-07-22T12:00:00Z",
            category="Test Event"
        )
        duplicate = SourceItem(
            external_id="one",
            title="Developing event",
            url="https://EXAMPLE.test/story?id=1&utm_medium=email",
            summary="Initial report",
            published_at="2026-07-22T12:00:00Z",
            category="Test Event"
        )
        changed = SourceItem(
            external_id="one",
            title="Developing event updated",
            url="https://example.test/story?id=1",
            summary="Revised report",
            published_at="2026-07-22T12:00:00Z",
            category="Test Event"
        )

        initial_result = self.store.ingest_items("fixture", [first])
        duplicate_result = self.store.ingest_items("fixture", [duplicate])
        update_result = self.store.ingest_items("fixture", [changed])
        documents = self.store.list_documents()

        self.assertEqual(1, initial_result.inserted)
        self.assertEqual(1, duplicate_result.duplicates)
        self.assertEqual(1, update_result.updated)
        self.assertEqual(1, len(documents))
        self.assertEqual("Developing event updated", documents[0]["title"])
        self.assertEqual(
            2,
            self.store.count_document_versions(documents[0]["id"])
        )
        self.assertEqual(2, len(self.store.outbox_since()))

    def test_canonicalize_url_removes_tracking_without_losing_query(self):
        self.assertEqual(
            "https://example.test/report?a=1&z=2",
            canonicalize_url(
                "HTTPS://Example.Test/report/?z=2&utm_source=x&a=1#section"
            )
        )

    def test_same_url_from_distinct_sources_preserves_provenance(self):
        self.store.register_source("second", "Second source", "test")
        item = SourceItem(
            external_id="shared",
            title="Shared evidence",
            url="https://example.test/shared"
        )

        self.store.ingest_items("fixture", [item])
        self.store.ingest_items("second", [item])

        documents = self.store.list_documents()
        self.assertEqual(2, len(documents))
        self.assertEqual(
            {"fixture", "second"},
            {document["source_id"] for document in documents}
        )

    def test_volatile_social_counters_do_not_create_revisions(self):
        initial = SourceItem(
            external_id="post", title="Same post",
            url="https://t.me/news/1",
            metadata={"platform": "telegram", "views": 10, "forwards": 1}
        )
        later = SourceItem(
            external_id="post", title="Same post",
            url="https://t.me/news/1",
            metadata={"platform": "telegram", "views": 500, "forwards": 20}
        )

        first = self.store.ingest_items("fixture", [initial])
        second = self.store.ingest_items("fixture", [later])
        document = self.store.list_documents()[0]

        self.assertEqual(1, first.inserted)
        self.assertEqual(1, second.duplicates)
        self.assertEqual(1, self.store.count_document_versions(document["id"]))


class UnderstandingEngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        path = Path(self.temporary_directory.name) / "understanding.db"
        self.store = IntelligenceStore(path)
        self.store.register_source(
            "source-a", "Source A", "test", credibility=0.9
        )
        self.store.register_source(
            "source-b", "Source B", "test", credibility=0.8
        )
        self.engine = UnderstandingEngine(self.store)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_private_mail_never_enters_public_world_model(self):
        self.store.register_source(
            "private-mail", "Private Mail", "private_mail", credibility=1.0
        )
        self.store.ingest_items("private-mail", [SourceItem(
            external_id="mail", title="Private claim",
            url="https://mail.test/message", category="private-mail",
            metadata={"visibility": "private"}
        )])

        result = self.engine.analyze_pending()

        self.assertEqual(0, result.documents_analyzed)
        self.assertEqual([], self.store.list_situations())

    def test_prediction_market_never_enters_factual_world_model(self):
        self.store.register_source(
            "polymarket", "Polymarket", "prediction_market", credibility=0.25
        )
        self.store.ingest_items("polymarket", [SourceItem(
            external_id="market", title="Will Example happen?",
            url="https://polymarket.com/event/example",
            summary="Market-implied probabilities: Yes 70%, No 30%.",
            category="prediction-market",
            metadata={"factual_evidence": False}
        )])

        result = self.engine.analyze_pending()
        reputation = ReputationEngine(
            self.store, maturity_hours=0
        ).evaluate()

        self.assertEqual(0, result.documents_analyzed)
        self.assertEqual(0, reputation.outcomes_recorded)
        self.assertEqual([], self.store.list_situations())
        self.assertEqual([], self.store.list_publisher_reputations())

    def test_deleted_social_post_is_retained_but_not_reanalyzed(self):
        self.store.ingest_items("source-a", [SourceItem(
            external_id="deleted", title="Deleted post",
            url="https://t.me/news/5", category="social-signal",
            metadata={"deleted": True}, status="deleted"
        )])

        result = self.engine.analyze_pending()

        self.assertEqual(0, result.documents_analyzed)
        self.assertEqual("deleted", self.store.list_documents()[0]["status"])


    def test_clusters_evidence_and_preserves_cross_source_contradiction(self):
        first = SourceItem(
            external_id="fire-a",
            title="Wildfire near Example Valley",
            url="https://a.test/fire",
            summary="The wildfire remains active.",
            published_at="2026-07-22T12:00:00Z",
            category="wildfires",
            latitude=40.0,
            longitude=-120.0,
            metadata={"status": "active", "place": "Example Valley"}
        )
        second = SourceItem(
            external_id="fire-b",
            title="Example Valley wildfire update",
            url="https://b.test/fire",
            summary="Officials describe the fire as contained.",
            published_at="2026-07-22T12:30:00Z",
            category="wildfires",
            latitude=40.02,
            longitude=-120.02,
            metadata={"status": "contained", "place": "Example Valley"}
        )
        self.store.ingest_items("source-a", [first])
        self.store.ingest_items("source-b", [second])

        result = self.engine.analyze_pending()
        situations = self.store.list_situations()
        detail = self.store.get_situation(situations[0]["id"])
        status_claims = [
            claim for claim in detail["claims"]
            if claim["predicate"] == "event.status"
        ]

        self.assertEqual(2, result.documents_analyzed)
        self.assertEqual(1, result.situations_created)
        self.assertEqual(1, len(situations))
        self.assertEqual("contested", situations[0]["status"])
        self.assertEqual(2, len(status_claims))
        self.assertEqual(
            {"contested"},
            {claim["status"] for claim in status_claims}
        )
        self.assertEqual(
            {"Source A", "Source B"},
            {
                evidence["source_name"]
                for claim in status_claims
                for evidence in claim["evidence"]
            }
        )
        self.assertTrue(
            all(
                evidence["document_version"] == 1
                for claim in status_claims
                for evidence in claim["evidence"]
            )
        )
        self.assertGreaterEqual(len(detail["timeline"]), 2)
        self.assertIn("unresolved contradictions", self.store.latest_briefing()["content"]["headline"])

    def test_thinking_model_synthesizes_all_cross_source_evidence(self):
        class ThinkingRouter:
            def __init__(self):
                self.routes = []

            def generate_json(self, prompt, **kwargs):
                self.routes.append(kwargs.get("routing"))
                return {
                    "conclusion": (
                        "The fire is active but containment is disputed; "
                        "independent reports agree on the location."
                    ),
                    "confidence": 0.82,
                    "stance": "contested",
                    "implications": ["Conditions may change while officials assess containment."],
                    "contradictions": ["Active versus contained status."],
                    "open_questions": ["Has containment held across the full perimeter?"]
                }

            def provider_name(self):
                return "local_thinking"

        router = ThinkingRouter()
        engine = UnderstandingEngine(self.store, router=router)
        first = SourceItem(
            external_id="thinking-a",
            title="Fire at Thinking Valley",
            url="https://a.test/thinking-fire",
            summary="The fire remains active.",
            published_at="2026-07-22T12:00:00Z",
            category="wildfires",
            latitude=40.0,
            longitude=-120.0,
            metadata={"status": "active", "place": "Thinking Valley"}
        )
        second = SourceItem(
            external_id="thinking-b",
            title="Thinking Valley fire update",
            url="https://b.test/thinking-fire",
            summary="Officials describe the fire as contained.",
            published_at="2026-07-22T12:30:00Z",
            category="wildfires",
            latitude=40.02,
            longitude=-120.02,
            metadata={"status": "contained", "place": "Thinking Valley"}
        )
        self.store.ingest_items("source-a", [first])
        self.store.ingest_items("source-b", [second])

        result = engine.analyze_pending()
        situation = self.store.list_situations()[0]
        detail = self.store.get_situation(situation["id"])

        self.assertEqual(["world_understanding"], router.routes)
        self.assertEqual(1, result.syntheses_created)
        self.assertEqual(
            "The fire is active but containment is disputed; independent reports agree on the location.",
            situation["worldview"]
        )
        self.assertEqual("local_thinking", detail["worldview_syntheses"][0]["model"])
        self.assertEqual(2, len(detail["worldview_syntheses"][0]["evidence"]))

    def test_forecasts_are_falsifiable_and_scored_after_resolution(self):
        from datetime import UTC, datetime, timedelta

        class Router:
            last_provider_name = "local_thinking"

            def __init__(self):
                self.calls = 0

            def generate_json(self, prompt, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "conclusion": "The fire is active.", "confidence": 0.8,
                        "stance": "probable", "implications": [],
                        "contradictions": [], "open_questions": []
                    }
                if self.calls == 2:
                    return {
                        "question": "Will the fire remain active?",
                        "predicted_outcome": "The fire will remain active.",
                        "probability": 0.8,
                        "target_at": (datetime.now(UTC) + timedelta(hours=8)).isoformat(),
                        "resolution_criteria": "A later official update states its status.",
                        "rationale": "Current official reports say it is active."
                    }
                return {"outcome": "yes", "summary": "A later official update confirms it."}

            def provider_name(self):
                return "local_thinking"

        router = Router()
        self.store.ingest_items("source-a", [SourceItem(
            external_id="forecast-a", title="Fire at Forecast Valley",
            url="https://a.test/forecast", summary="The fire remains active.",
            category="wildfires", published_at="2026-07-22T12:00:00Z"
        )])
        UnderstandingEngine(self.store, router=router).analyze_pending()
        forecaster = ForecastEngine(self.store, router, max_active=2)

        self.assertEqual(1, forecaster.create_forecasts())
        forecast = self.store.list_forecasts()[0]
        self.assertEqual("active", forecast["status"])
        self.assertLessEqual(forecast["probability"], 0.69)
        self.assertEqual("source-a", forecast["evidence"][0]["source_id"])
        self.assertEqual(0.9, forecast["evidence"][0]["source_credibility"])
        self.store.resolve_forecast(
            forecast["id"], "yes", "Confirmed by later evidence.", [],
            "2026-07-24T00:00:00Z"
        )
        resolved = self.store.list_forecasts()[0]
        self.assertEqual("resolved", resolved["status"])
        self.assertEqual(1, resolved["actual_outcome"])
        self.assertAlmostEqual((0.69 - 1) ** 2, resolved["brier_score"])

    def test_distinct_nws_offices_are_not_merged_into_one_situation(self):
        self.store.ingest_items("source-a", [SourceItem(
            external_id="nws-a",
            title=(
                "Heat Advisory issued July 23 by NWS Pocatello ID"
            ),
            url="https://a.test/pocatello",
            summary="High temperatures are expected in southeastern Idaho.",
            category="weather-alert"
        )])
        self.store.ingest_items("source-b", [SourceItem(
            external_id="nws-b",
            title=(
                "Heat Advisory issued July 23 by NWS El Paso TX"
            ),
            url="https://b.test/el-paso",
            summary="High temperatures are expected in west Texas.",
            category="weather-alert"
        )])

        self.engine.analyze_pending()

        self.assertEqual(2, len(self.store.list_situations()))

    def test_new_source_revision_supersedes_old_claim_and_is_restart_safe(self):
        initial = SourceItem(
            external_id="quake",
            title="Earthquake near Test City",
            url="https://a.test/quake",
            published_at="2026-07-22T12:00:00Z",
            category="earthquake",
            latitude=35.0,
            longitude=-110.0,
            metadata={"status": "preliminary", "magnitude": 4.8}
        )
        revised = SourceItem(
            external_id="quake",
            title="Earthquake near Test City",
            url="https://a.test/quake",
            published_at="2026-07-22T12:00:00Z",
            category="earthquake",
            latitude=35.0,
            longitude=-110.0,
            metadata={"status": "reviewed", "magnitude": 4.9}
        )
        self.store.ingest_items("source-a", [initial])
        self.engine.analyze_pending()
        self.store.ingest_items("source-a", [revised])
        result = self.engine.analyze_pending()
        situation = self.store.list_situations()[0]
        detail = self.store.get_situation(situation["id"])
        statuses = {
            claim["object"]: claim["status"]
            for claim in detail["claims"]
            if claim["predicate"] == "event.status"
        }

        self.assertEqual(1, result.documents_analyzed)
        self.assertEqual("superseded", statuses["preliminary"])
        self.assertEqual("active", statuses["reviewed"])
        self.assertEqual("active", situation["status"])
        self.assertEqual(0, UnderstandingEngine(self.store).analyze_pending().documents_analyzed)


class ReputationEngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = IntelligenceStore(
            Path(self.temporary_directory.name) / "reputation.db"
        )
        self.store.register_source(
            "telegram", "Telegram", "social_signal", credibility=0.3
        )
        self.store.register_source(
            "official", "Official Agency", "public_api", credibility=0.95
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_later_independent_authority_increases_early_publisher_trust(self):
        early = SourceItem(
            external_id="early", title="Earthquake near Example City",
            url="https://t.me/earlywire/1", category="earthquake",
            published_at="2026-07-20T10:00:00Z",
            metadata={
                "platform": "telegram", "channel_username": "earlywire"
            }
        )
        confirmed = SourceItem(
            external_id="official", title="Earthquake near Example City",
            url="https://official.test/quake", category="earthquake",
            published_at="2026-07-20T11:00:00Z"
        )
        self.store.ingest_items("telegram", [early])
        self.store.ingest_items("official", [confirmed])
        UnderstandingEngine(self.store).analyze_pending()

        result = ReputationEngine(
            self.store, maturity_hours=0
        ).evaluate()
        reputation = {
            row["publisher_key"]: row
            for row in self.store.list_publisher_reputations()
        }["telegram:earlywire"]

        self.assertEqual(1, result.outcomes_recorded)
        self.assertEqual(1, reputation["confirmed_count"])
        self.assertGreater(reputation["learned_credibility"], 0.3)
        self.assertLessEqual(reputation["learned_credibility"], 0.45)

    def test_deleted_unverified_post_lowers_trust_without_erasing_baseline(self):
        self.store.ingest_items("telegram", [SourceItem(
            external_id="deleted", title="Unverified deleted report",
            url="https://t.me/noisywire/2", category="social-signal",
            published_at="2026-07-20T10:00:00Z", status="deleted",
            metadata={
                "platform": "telegram", "channel_username": "noisywire",
                "deleted": True
            }
        )])

        ReputationEngine(self.store, maturity_hours=0).evaluate()
        reputation = self.store.list_publisher_reputations()[0]

        self.assertEqual("telegram:noisywire", reputation["publisher_key"])
        self.assertEqual(1, reputation["deleted_unverified_count"])
        self.assertLess(reputation["learned_credibility"], 0.3)
        self.assertGreaterEqual(reputation["learned_credibility"], 0.15)

    def test_publisher_with_no_outcome_keeps_exact_baseline(self):
        self.store.ingest_items("official", [SourceItem(
            external_id="unresolved", title="Unresolved official notice",
            url="https://official.test/unresolved",
            published_at="2026-07-20T10:00:00Z"
        )])

        result = ReputationEngine(self.store, maturity_hours=0).evaluate()
        reputation = self.store.list_publisher_reputations()[0]

        self.assertEqual(0, result.outcomes_recorded)
        self.assertEqual(0, result.publishers_updated)
        self.assertEqual(0.95, reputation["baseline_credibility"])
        self.assertEqual(0.95, reputation["learned_credibility"])

    def test_every_public_publisher_gets_a_profile_before_maturity(self):
        from datetime import UTC, datetime

        self.store.ingest_items("official", [SourceItem(
            external_id="fresh", title="Fresh official report",
            url="https://official.test/fresh",
            published_at=datetime.now(UTC).isoformat()
        )])

        ReputationEngine(self.store, maturity_hours=72).evaluate()
        reputation = self.store.list_publisher_reputations()[0]

        self.assertEqual("official", reputation["publisher_key"])
        self.assertEqual(0, reputation["evaluated_count"])
        self.assertEqual(0.95, reputation["learned_credibility"])


class ConnectorTests(unittest.TestCase):
    def test_news_connector_normalizes_rss_with_publisher_provenance(self):
        xml = b"""<?xml version='1.0'?>
        <rss xmlns:dc='http://purl.org/dc/elements/1.1/' version='2.0'>
          <channel><item>
            <guid>story-1</guid><title>World &amp; regional update</title>
            <link>https://news.example/story/1</link>
            <description><![CDATA[<p>Verified <b>report</b>.</p>]]></description>
            <pubDate>Wed, 22 Jul 2026 12:00:00 GMT</pubDate>
            <dc:creator>News Desk</dc:creator><category>World</category>
          </item></channel>
        </rss>"""
        connector = NewsFeedConnector(
            "Example News", "https://feeds.example/world.xml",
            credibility=0.82, fetch_xml=lambda _: xml
        )

        item = connector.poll().items[0]

        self.assertEqual("traditional_news", connector.kind)
        self.assertEqual("World & regional update", item.title)
        self.assertEqual("Verified report.", item.summary)
        self.assertEqual("news.example", item.metadata["domain"])
        self.assertEqual("News Desk", item.metadata["author"])
        self.assertEqual(["World"], item.metadata["feed_categories"])

    def test_news_connector_normalizes_atom(self):
        xml = b"""<feed xmlns='http://www.w3.org/2005/Atom'>
          <entry><id>tag:example,1</id><title>Atom report</title>
          <link rel='alternate' href='https://atom.example/report'/>
          <summary>Short report</summary>
          <updated>2026-07-22T12:00:00Z</updated>
          <category term='Politics'/></entry></feed>"""
        connector = NewsFeedConnector(
            "Atom News", "https://atom.example/feed",
            fetch_xml=lambda _: xml
        )

        item = connector.poll().items[0]

        self.assertEqual("tag:example,1", item.external_id)
        self.assertEqual("https://atom.example/report", item.url)
        self.assertEqual(["Politics"], item.metadata["feed_categories"])

    def test_polymarket_connector_labels_prices_as_nonfactual_signal(self):
        connector = PolymarketConnector(fetch_json=lambda _: [{
            "id": "42",
            "question": "Will Example happen?",
            "slug": "will-example-happen",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.63", "0.37"]',
            "createdAt": "2026-07-20T10:00:00Z",
            "updatedAt": "2026-07-22T12:00:00Z",
            "volume": "12000.5",
            "volume24hr": 500,
            "liquidity": "3000",
            "events": [{"slug": "example-event", "title": "Example"}]
        }], max_items=10)

        item = connector.poll().items[0]

        self.assertEqual("prediction_market", connector.kind)
        self.assertIn("Yes 63%", item.summary)
        self.assertIn("not verified facts", item.summary)
        self.assertFalse(item.metadata["factual_evidence"])
        self.assertEqual(
            "https://polymarket.com/event/example-event/will-example-happen",
            item.url
        )
        self.assertNotIn("updatedAt", item.metadata)

    def test_polymarket_volume_changes_do_not_version_but_prices_do(self):
        with tempfile.TemporaryDirectory() as directory:
            store = IntelligenceStore(Path(directory) / "market.db")
            store.register_source(
                "polymarket", "Polymarket", "prediction_market"
            )
            initial = SourceItem(
                external_id="42", title="Will Example happen?",
                url="https://polymarket.com/event/example",
                summary="Market-implied probabilities: Yes 63%, No 37%.",
                published_at="2026-07-20T10:00:00Z",
                category="prediction-market",
                metadata={"volume": 100, "volume_24h": 10, "liquidity": 50}
            )
            volume_only = SourceItem(
                external_id="42", title=initial.title, url=initial.url,
                summary=initial.summary, published_at=initial.published_at,
                category=initial.category,
                metadata={"volume": 500, "volume_24h": 40, "liquidity": 80}
            )
            changed_odds = SourceItem(
                external_id="42", title=initial.title, url=initial.url,
                summary="Market-implied probabilities: Yes 70%, No 30%.",
                published_at=initial.published_at, category=initial.category,
                metadata={"volume": 500, "volume_24h": 40, "liquidity": 80}
            )

            store.ingest_items("polymarket", [initial])
            volume_result = store.ingest_items("polymarket", [volume_only])
            odds_result = store.ingest_items("polymarket", [changed_odds])
            document = store.list_documents()[0]

            self.assertEqual(1, volume_result.duplicates)
            self.assertEqual(1, odds_result.updated)
            self.assertEqual(2, store.count_document_versions(document["id"]))

    def test_x_connector_collects_curated_accounts_and_searches_read_only(self):
        calls = []

        def fetch_api(url):
            calls.append(url)
            post = {
                "id": "200",
                "text": "Earthquake update for Example Region",
                "author_id": "123",
                "created_at": "2026-07-22T12:00:00Z",
                "conversation_id": "200",
                "lang": "en",
                "public_metrics": {"retweet_count": 4}
            }
            return {
                "data": [post],
                "includes": {
                    "users": [{
                        "id": "123",
                        "name": "Public Agency",
                        "username": "PublicAgency",
                        "verified": True,
                        "public_metrics": {"followers_count": 1000}
                    }]
                }
            }

        connector = XConnector(
            bearer_token="secret-token",
            usernames=("@PublicAgency", "not valid!"),
            search_queries=("earthquake lang:en -is:retweet",),
            fetch_api=fetch_api,
            max_items=10,
            enabled=True
        )
        first = connector.poll()
        second = connector.poll(first.cursor)
        item = first.items[0]

        self.assertEqual(1, len(first.items))
        self.assertEqual("earthquake", item.category)
        self.assertEqual("PublicAgency", item.metadata["author_username"])
        self.assertEqual(
            [
                "recent-search:(from:PublicAgency OR "
                "(earthquake lang:en -is:retweet)) -is:retweet"
            ],
            item.metadata["collection_contexts"]
        )
        self.assertTrue(any("since_id=200" in url for url in calls))
        self.assertTrue(all("secret-token" not in url for url in calls))
        self.assertTrue(all("not+valid" not in url for url in calls))
        self.assertIn("200", second.cursor["search_since_ids"].values())

    def test_x_connector_requires_token_and_explicit_targets(self):
        self.assertFalse(XConnector(bearer_token="", usernames=("NOAA",)).enabled)
        self.assertFalse(XConnector(bearer_token="token", usernames=()).enabled)

    def test_gmail_connector_reads_messages_without_mutating_mailbox(self):
        encoded_body = base64.urlsafe_b64encode(
            b"Private message body"
        ).decode("ascii")

        class Result:
            def __init__(self, value):
                self.value = value

            def execute(self):
                return self.value

        class Messages:
            def list(self, **kwargs):
                self.list_args = kwargs
                return Result({"messages": [{"id": "gmail-1"}]})

            def get(self, **kwargs):
                self.get_args = kwargs
                return Result({
                    "id": "gmail-1",
                    "threadId": "thread-1",
                    "snippet": "Private preview",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Private update"},
                            {"name": "From", "value": "source@example.test"},
                            {"name": "Date", "value": "Wed, 22 Jul 2026 12:00:00 +0000"}
                        ],
                        "mimeType": "text/plain",
                        "body": {"data": encoded_body}
                    }
                })

        messages = Messages()

        class Service:
            def users(self):
                return self

            def messages(self):
                return messages

        connector = GmailConnector(
            service=Service(),
            store_body=True,
            enabled=True,
            max_items=5
        )
        item = connector.poll().items[0]

        self.assertEqual("Private update", item.title)
        self.assertEqual("Private message body", item.content)
        self.assertEqual("private", item.metadata["visibility"])
        self.assertEqual("full", messages.get_args["format"])
        self.assertFalse(messages.list_args["includeSpamTrash"])

    def test_outlook_connector_uses_read_only_graph_listing(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "outlook.json"
            cache.write_text("{}", encoding="utf-8")
            calls = []
            connector = OutlookConnector(
                client_id="client-id",
                token_cache_path=cache,
                store_body=False,
                fetch_graph=lambda url, token: calls.append((url, token)) or {
                    "value": [{
                        "id": "outlook-1",
                        "internetMessageId": "<one@example.test>",
                        "subject": "Outlook update",
                        "receivedDateTime": "2026-07-22T12:00:00Z",
                        "from": {"emailAddress": {"address": "source@example.test"}},
                        "bodyPreview": "A private preview",
                        "webLink": "https://outlook.office.com/mail/deeplink/read/one",
                        "isRead": False,
                        "categories": []
                    }]
                },
                enabled=True
            )
            connector._access_token = lambda: "test-token"
            item = connector.poll().items[0]

        self.assertEqual("Outlook update", item.title)
        self.assertEqual("", item.content)
        self.assertEqual("outlook", item.metadata["mail_provider"])
        self.assertEqual("test-token", calls[0][1])
        self.assertIn("%24select=", calls[0][0])
        self.assertNotIn("Mail.ReadWrite", calls[0][0])

    def test_secure_token_writer_sets_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token.json"
            secure_write(path, '{"token":"secret"}')
            self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_usgs_connector_normalizes_geojson(self):
        connector = UsgsConnector(
            fetch_json=lambda _: {
                "metadata": {"generated": 1784730000000},
                "features": [
                    {
                        "id": "us-test",
                        "properties": {
                            "mag": 5.1,
                            "place": "Test Region",
                            "time": 1784728800000,
                            "updated": 1784729900000,
                            "url": "https://earthquake.test/us-test",
                            "title": "M 5.1 - Test Region",
                            "sig": 400,
                            "status": "reviewed",
                            "tsunami": 0
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [-70.5, 18.4, 12.0]
                        }
                    }
                ]
            }
        )
        batch = connector.poll()
        item = batch.items[0]

        self.assertEqual("us-test", item.external_id)
        self.assertEqual("earthquake", item.category)
        self.assertEqual(18.4, item.latitude)
        self.assertEqual(-70.5, item.longitude)
        self.assertEqual(12.0, item.metadata["depth_km"])

    def test_eonet_connector_normalizes_open_event(self):
        connector = EonetConnector(
            fetch_json=lambda _: {
                "events": [
                    {
                        "id": "EONET_1",
                        "title": "Test wildfire",
                        "description": "Active wildfire",
                        "link": "https://eonet.test/events/EONET_1",
                        "closed": None,
                        "categories": [{"id": "wildfires", "title": "Wildfires"}],
                        "sources": [{"id": "source", "url": "https://source.test"}],
                        "geometry": [
                            {
                                "date": "2026-07-22T12:00:00Z",
                                "type": "Point",
                                "coordinates": [-120.0, 40.0]
                            }
                        ]
                    }
                ]
            }
        )
        item = connector.poll().items[0]

        self.assertEqual("Wildfires", item.category)
        self.assertEqual(40.0, item.latitude)
        self.assertEqual(-120.0, item.longitude)
        self.assertEqual(1, item.metadata["geometry_count"])

    def test_reliefweb_requires_appname_and_normalizes_report(self):
        calls = []
        disabled = ReliefWebConnector(appname="", fetch_json=calls.append)
        self.assertFalse(disabled.enabled)
        self.assertEqual([], disabled.poll().items)
        self.assertEqual([], calls)

        connector = ReliefWebConnector(
            appname="entity.example",
            fetch_json=lambda _: {
                "data": [
                    {
                        "id": 42,
                        "fields": {
                            "title": "Humanitarian update",
                            "url": "https://reliefweb.int/report/test",
                            "body": "<p>Situation update.</p>",
                            "date": {"created": "2026-07-22T12:00:00Z"},
                            "country": [{"name": "Example"}],
                            "source": [{"name": "Example Agency"}]
                        }
                    }
                ]
            }
        )
        item = connector.poll().items[0]

        self.assertEqual("42", item.external_id)
        self.assertEqual("humanitarian", item.category)
        self.assertEqual(["Example"], item.metadata["countries"])
        self.assertNotIn("<p>", item.summary)

    def test_gdacs_connector_normalizes_rss_alert(self):
        xml = b"""<rss xmlns:gdacs="http://www.gdacs.org">
          <channel><item><guid>gdacs-1</guid><title>Red earthquake</title>
          <link>https://gdacs.test/1</link><description>&lt;b&gt;Alert&lt;/b&gt;</description>
          <pubDate>Wed, 22 Jul 2026 12:00:00 GMT</pubDate>
          <gdacs:alertlevel>Red</gdacs:alertlevel>
          <gdacs:eventtype>EQ</gdacs:eventtype>
          <gdacs:country>Example</gdacs:country>
          <gdacs:point>18.4 -70.5</gdacs:point></item></channel></rss>"""
        item = GdacsConnector(fetch_xml=lambda _: xml).poll().items[0]

        self.assertEqual("gdacs-1", item.external_id)
        self.assertEqual("earthquake", item.category)
        self.assertEqual(18.4, item.latitude)
        self.assertEqual(-70.5, item.longitude)
        self.assertEqual("Red", item.metadata["alert_level"])
        self.assertEqual("Alert", item.summary)

    def test_who_connector_normalizes_outbreak_notice(self):
        connector = WhoOutbreakConnector(fetch_json=lambda _: {"value": [{
            "Id": "don-1", "Title": "Disease outbreak",
            "Summary": "<p>Situation update.</p>",
            "PublicationDateAndTime": "2026-07-22T12:00:00Z",
            "ItemDefaultUrl": "/emergencies/disease-outbreak-news/item/1"
        }]})
        item = connector.poll().items[0]

        self.assertEqual("don-1", item.external_id)
        self.assertEqual("disease-outbreak", item.category)
        self.assertEqual("Situation update.", item.summary)
        self.assertTrue(item.url.startswith("https://www.who.int/"))

    def test_nws_connector_normalizes_active_alert(self):
        connector = NwsAlertsConnector(fetch_json=lambda _: {"features": [{
            "id": "https://api.weather.gov/alerts/test",
            "properties": {
                "event": "Tornado Warning",
                "headline": "Tornado Warning issued",
                "description": "Take shelter.",
                "instruction": "Move to an interior room.",
                "sent": "2026-07-22T12:00:00Z",
                "severity": "Extreme", "areaDesc": "Example County"
            }
        }]})
        item = connector.poll().items[0]

        self.assertEqual("severe-storms", item.category)
        self.assertIn("Instructions:", item.summary)
        self.assertEqual("Extreme", item.metadata["severity"])

    def test_cisa_kev_connector_normalizes_catalog_entry(self):
        connector = CisaKevConnector(fetch_json=lambda _: {
            "catalogVersion": "2026.07.23",
            "vulnerabilities": [{
                "cveID": "CVE-2026-12345",
                "vendorProject": "Example",
                "product": "Gateway",
                "shortDescription": "Actively exploited issue.",
                "requiredAction": "Apply the vendor fix.",
                "dateAdded": "2026-07-23",
                "dueDate": "2026-08-01",
                "knownRansomwareCampaignUse": "Known"
            }]
        })
        item = connector.poll().items[0]

        self.assertEqual("CVE-2026-12345", item.external_id)
        self.assertEqual("known-exploited-vulnerability", item.category)
        self.assertIn("Required action:", item.summary)
        self.assertEqual("Known", item.metadata["known_ransomware_campaign_use"])

    def test_github_advisories_connector_normalizes_public_advisory(self):
        connector = GitHubAdvisoriesConnector(fetch_json=lambda _: [{
            "ghsa_id": "GHSA-test-1234",
            "cve_id": "CVE-2026-54321",
            "html_url": "https://github.com/advisories/GHSA-test-1234",
            "summary": "Example advisory",
            "description": "A vulnerable dependency.",
            "published_at": "2026-07-23T12:00:00Z",
            "severity": "high",
            "cvss": {"score": 8.1}, "cwes": [{"cwe_id": "CWE-79"}]
        }])
        item = connector.poll().items[0]

        self.assertEqual("GHSA-test-1234", item.external_id)
        self.assertEqual("software-vulnerability", item.category)
        self.assertEqual("high", item.metadata["severity"])

    def test_noaa_space_weather_connector_normalizes_alert(self):
        connector = NoaaSpaceWeatherConnector(fetch_json=lambda _: [{
            "product_id": "ALTX3",
            "product_name": "Space Weather Alert",
            "issue_datetime": "2026-07-23T12:00:00Z",
            "message": "Geomagnetic conditions are elevated."
        }])
        item = connector.poll().items[0]

        self.assertEqual("ALTX3", item.external_id)
        self.assertEqual("space-weather", item.category)
        self.assertIn("Geomagnetic", item.summary)

    def test_firms_requires_explicit_key_and_normalizes_detection(self):
        self.assertFalse(FirmsConnector(map_key="", enabled=True).enabled)
        connector = FirmsConnector(
            map_key="test-key", enabled=True,
            fetch_csv=lambda _: (
                "latitude,longitude,bright_ti4,confidence,acq_date,acq_time,frp,daynight\n"
                "40.12,-120.50,345.5,h,2026-07-23,0345,18.2,N\n"
            )
        )
        item = connector.poll().items[0]

        self.assertEqual("wildfire", item.category)
        self.assertEqual(40.12, item.latitude)
        self.assertEqual(-120.5, item.longitude)
        self.assertEqual("h", item.metadata["confidence"])

    def test_firms_redacts_map_key_from_collector_errors(self):
        connector = FirmsConnector(
            map_key="private-map-key", enabled=True,
            fetch_csv=lambda url: (_ for _ in ()).throw(RuntimeError(url))
        )
        with self.assertRaisesRegex(RuntimeError, r"\[REDACTED\]") as context:
            connector.poll()
        self.assertNotIn("private-map-key", str(context.exception))

    def test_world_bank_connector_normalizes_latest_indicator(self):
        connector = WorldBankIndicatorsConnector(
            countries=("WLD",), indicators=("FP.CPI.TOTL.ZG",),
            fetch_json=lambda _: [{"page": 1}, [{
                "date": "2025", "value": 3.4, "unit": "",
                "country": {"value": "World"},
                "indicator": {"value": "Inflation, consumer prices"}
            }]]
        )
        item = connector.poll().items[0]

        self.assertEqual("WLD:FP.CPI.TOTL.ZG:2025", item.external_id)
        self.assertEqual("economic-indicator", item.category)
        self.assertEqual(3.4, item.metadata["value"])

    def test_fred_requires_explicit_key_and_redacts_it_from_errors(self):
        self.assertFalse(FredConnector(api_key="", series=("UNRATE",), enabled=True).enabled)
        connector = FredConnector(
            api_key="private-fred-key", series=("UNRATE",), enabled=True,
            fetch_json=lambda _: {"observations": [
                {"date": "2026-07-01", "value": "4.1"},
                {"date": "2026-06-01", "value": "4.0"}
            ]}
        )
        item = connector.poll().items[0]
        self.assertEqual("UNRATE:2026-07-01", item.external_id)
        self.assertEqual(0.1, round(item.metadata["change"], 4))

        failing = FredConnector(
            api_key="private-fred-key", series=("UNRATE",), enabled=True,
            fetch_json=lambda url: (_ for _ in ()).throw(RuntimeError(url))
        )
        with self.assertRaisesRegex(RuntimeError, r"\[REDACTED\]") as context:
            failing.poll()
        self.assertNotIn("private-fred-key", str(context.exception))

    def test_gdelt_requires_queries_and_deduplicates_articles(self):
        disabled = GdeltConnector(queries=(), enabled=True)
        self.assertFalse(disabled.enabled)
        payload = {"articles": [{
            "url": "https://news.test/report", "title": "World report",
            "seendate": "20260722T120000Z", "domain": "news.test",
            "language": "English"
        }]}
        connector = GdeltConnector(
            queries=("earthquake", "flood"), max_items=10,
            fetch_json=lambda _: payload
        )
        batch = connector.poll()

        self.assertEqual(1, len(batch.items))
        self.assertEqual("world-news", batch.items[0].category)
        self.assertEqual("2026-07-22T12:00:00Z", batch.items[0].published_at)

    def test_telegram_requires_credentials_channels_and_explicit_enable(self):
        self.assertFalse(TelegramConnector(enabled=True).enabled)
        self.assertFalse(TelegramConnector(
            api_id="123", api_hash="hash", enabled=True
        ).enabled)

    def test_telegram_collects_public_text_edits_and_deletion_tombstones(self):
        calls = []

        class Gateway:
            def collect(self, channels, previous, limit):
                calls.append((channels, previous, limit))
                return [{
                    "id": 42, "username": "world_news", "title": "World News",
                    "message_ids": [11], "deleted_ids": [10],
                    "messages": [{
                        "id": 11, "text": "Developing report", "date": "2026-07-22T12:00:00Z",
                        "edit_date": "2026-07-22T12:01:00Z", "views": 100,
                        "forwards": 2, "forwarded": False, "media_type": None
                    }]
                }]

        connector = TelegramConnector(
            api_id="123", api_hash="hash", channels=("@world_news",),
            gateway=Gateway(), enabled=True
        )
        batch = connector.poll({"known_message_ids": {"42": [10]}})

        self.assertEqual(2, len(batch.items))
        active, deleted = batch.items
        self.assertEqual("42:11", active.external_id)
        self.assertEqual("pending", active.metadata["translation_status"])
        self.assertEqual("deleted", deleted.status)
        self.assertTrue(deleted.metadata["deleted"])
        self.assertEqual({"42": [11]}, batch.cursor["known_message_ids"])
        self.assertEqual(("world_news",), calls[0][0])

    def test_store_preserves_original_version_when_public_post_is_deleted(self):
        original = SourceItem(
            external_id="42:10", title="Original post",
            url="https://t.me/world_news/10", content="Original public text",
            metadata={"platform": "telegram"}
        )
        deleted = SourceItem(
            external_id="42:10", title="Deleted Telegram post",
            url="https://t.me/world_news/10", summary="Deleted",
            metadata={"platform": "telegram", "deleted": True}, status="deleted"
        )
        with tempfile.TemporaryDirectory() as directory:
            store = IntelligenceStore(Path(directory) / "telegram.db")
            store.register_source("telegram", "Telegram", "social_signal")
            store.ingest_items("telegram", [original])
            store.ingest_items("telegram", [deleted])
            document = store.list_documents()[0]

            self.assertEqual("deleted", document["status"])
            self.assertEqual(2, store.count_document_versions(document["id"]))


class IntelligenceWorkerTests(unittest.TestCase):
    def test_worker_advances_cursor_and_does_not_duplicate_on_restart(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = IntelligenceStore(Path(temporary_directory) / "world.db")

            class FixtureConnector:
                source_id = "fixture"
                name = "Fixture"
                kind = "test"
                base_url = "https://example.test"
                credibility = 0.5
                poll_seconds = 60
                enabled = True

                def poll(self, cursor=None):
                    return ConnectorBatch(
                        items=[
                            SourceItem(
                                external_id="one",
                                title="One",
                                url="https://example.test/one"
                            )
                        ],
                        cursor={"token": "next"}
                    )

            first = IntelligenceWorker(store, [FixtureConnector()])
            second = IntelligenceWorker(store, [FixtureConnector()])
            first_outcome = first.run_once(force=True)[0]
            second_outcome = second.run_once(force=True)[0]

            self.assertEqual(1, first_outcome.result.inserted)
            self.assertEqual(1, second_outcome.result.duplicates)
            self.assertEqual({"token": "next"}, store.source_cursor("fixture"))
            self.assertEqual(1, store.overview()["documents"])

    def test_worker_reports_collection_analysis_and_completion_activity(self):
        with tempfile.TemporaryDirectory() as directory:
            store = IntelligenceStore(Path(directory) / "activity.db")

            class Connector:
                source_id = "activity"
                name = "Activity fixture"
                kind = "test"
                base_url = "https://example.test"
                credibility = 0.5
                poll_seconds = 60
                enabled = True

                def poll(self, cursor=None):
                    return ConnectorBatch(items=[SourceItem(
                        external_id="one", title="World event",
                        url="https://example.test/world-event"
                    )])

            events = []
            worker = IntelligenceWorker(
                store, [Connector()],
                on_activity=lambda state, **details: events.append(
                    (state, details)
                )
            )
            worker.run_once(force=True)

            self.assertEqual(
                [
                    "intelligence_collecting",
                    "world_model_updating",
                    "intelligence_finished"
                ],
                [state for state, _ in events]
            )
            self.assertEqual(1, events[-1][1]["changed_documents"])
            self.assertEqual(1, events[-1][1]["documents_analyzed"])

    def test_worker_describes_empty_poll_as_sources_current(self):
        with tempfile.TemporaryDirectory() as directory:
            store = IntelligenceStore(Path(directory) / "empty.db")

            class Connector:
                source_id = "empty"
                name = "Empty fixture"
                kind = "test"
                base_url = "https://example.test"
                credibility = 0.5
                poll_seconds = 60
                enabled = True

                def poll(self, cursor=None):
                    return ConnectorBatch()

            events = []
            worker = IntelligenceWorker(
                store, [Connector()],
                on_activity=lambda state, **details: events.append(
                    (state, details)
                )
            )
            worker.run_once(force=True)

            self.assertEqual("intelligence_finished", events[-1][0])
            self.assertEqual(
                "Sources checked; no new or revised evidence",
                events[-1][1]["message"]
            )


class IntelligenceDashboardTests(unittest.TestCase):
    def test_dashboard_serves_static_page_and_json_api(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            store = IntelligenceStore(temporary / "world.db")
            store.register_source("fixture", "Fixture", "test")
            store.ingest_items(
                "fixture",
                [
                    SourceItem(
                        external_id="one",
                        title="Dashboard evidence",
                        url="https://example.test/evidence",
                        summary="Evidence summary"
                    )
                ]
            )
            UnderstandingEngine(store).analyze_pending()
            static_root = temporary / "dashboard"
            static_root.mkdir()
            (static_root / "index.html").write_text(
                "<!doctype html><title>Intelligence test</title>",
                encoding="utf-8"
            )
            dashboard = IntelligenceDashboard(
                store,
                host="127.0.0.1",
                port=0,
                static_root=static_root
            )

            try:
                dashboard.start()
                with urllib.request.urlopen(dashboard.url, timeout=2) as response:
                    page = response.read().decode("utf-8")
                with urllib.request.urlopen(
                    dashboard.url + "api/intelligence/documents",
                    timeout=2
                ) as response:
                    payload = json.loads(response.read())
                with urllib.request.urlopen(
                    dashboard.url + "api/intelligence/situations",
                    timeout=2
                ) as response:
                    situations = json.loads(response.read())["situations"]
                with urllib.request.urlopen(
                    dashboard.url
                    + "api/intelligence/situations/"
                    + situations[0]["id"],
                    timeout=2
                ) as response:
                    situation_detail = json.loads(response.read())
                with urllib.request.urlopen(
                    dashboard.url + "api/intelligence/briefing",
                    timeout=2
                ) as response:
                    briefing = json.loads(response.read())
                with urllib.request.urlopen(
                    dashboard.url + "api/intelligence/reputations",
                    timeout=2
                ) as response:
                    reputations = json.loads(response.read())

                self.assertIn("Intelligence test", page)
                self.assertEqual(
                    "Dashboard evidence",
                    payload["documents"][0]["title"]
                )
                self.assertEqual(1, len(situations))
                self.assertGreater(len(situation_detail["claims"]), 0)
                self.assertEqual(1, briefing["situation_count"])
                self.assertIn("reputations", reputations)
            finally:
                dashboard.stop()

    def test_disabled_service_does_not_create_database(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "disabled.db"
            service = IntelligenceService(
                IntelligenceConfig(enabled=False, database_path=path)
            )
            service.start()

            self.assertFalse(path.exists())
            self.assertIn("disabled", service.setup_status().lower())

    def test_private_mail_rejects_non_local_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            config = IntelligenceConfig(
                enabled=True,
                database_path=Path(directory) / "private.db",
                dashboard_host="0.0.0.0",
                gmail_enabled=True
            )
            with self.assertRaisesRegex(RuntimeError, "localhost"):
                IntelligenceService(config)


if __name__ == "__main__":
    unittest.main()
