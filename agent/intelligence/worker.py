import threading
import time
from dataclasses import dataclass

from agent.connectors import (
    CisaKevConnector,
    EonetConnector,
    FirmsConnector,
    FredConnector,
    GdacsConnector,
    GdeltConnector,
    GmailConnector,
    GitHubAdvisoriesConnector,
    OutlookConnector,
    NwsAlertsConnector,
    NoaaSpaceWeatherConnector,
    NewsFeedConnector,
    PolymarketConnector,
    ReliefWebConnector,
    TelegramConnector,
    UsgsConnector,
    WhoOutbreakConnector,
    WorldBankIndicatorsConnector,
    XConnector
)
from agent.intelligence.models import IngestResult
from agent.intelligence.reputation import ReputationEngine, ReputationResult
from agent.intelligence.understanding import AnalysisResult, UnderstandingEngine
from agent.intelligence.forecasting import ForecastEngine
from agent.intelligence.clustering import EventClusterer
from agent.intelligence.embeddings import OllamaEmbeddingProvider


@dataclass(frozen=True)
class PollOutcome:
    source_id: str
    fetched: int
    result: IngestResult
    error: str = ""


class IntelligenceWorker:
    def __init__(
        self,
        store,
        connectors,
        loop_seconds=30,
        understanding=None,
        reputation=None,
        forecasting=None,
        forecast_max_active=12,
        forecast_per_cycle=2,
        analysis_poll_seconds=300,
        forecast_poll_seconds=900,
        source_backoff_max_seconds=21600,
        activity_watchdog_seconds=90,
        on_activity=None
    ):
        self.store = store
        self.connectors = list(connectors)
        self.loop_seconds = max(1, int(loop_seconds))
        self.understanding = (
            UnderstandingEngine(store)
            if understanding is None
            else understanding
        )
        self.last_analysis_result = AnalysisResult()
        self.reputation = reputation or ReputationEngine(store)
        self.last_reputation_result = ReputationResult()
        self.forecasting = forecasting or ForecastEngine(
            store, router=self.understanding.router,
            max_active=forecast_max_active, per_cycle=forecast_per_cycle
        )
        self.last_forecast_result = {"created": 0, "resolved": 0}
        self.analysis_poll_seconds = max(30, int(analysis_poll_seconds))
        self.forecast_poll_seconds = max(60, int(forecast_poll_seconds))
        self.source_backoff_max_seconds = max(
            60, int(source_backoff_max_seconds)
        )
        self.activity_watchdog_seconds = max(
            15, min(900, int(activity_watchdog_seconds))
        )
        self._next_analysis_at = 0.0
        self._next_forecast_at = 0.0
        self._source_failures = {}
        self._source_retry_at = {}
        self.on_activity = on_activity
        self._stop = threading.Event()
        self._thread = None

        for connector in self.connectors:
            self.store.register_source(
                source_id=connector.source_id,
                name=connector.name,
                kind=connector.kind,
                base_url=connector.base_url,
                credibility=connector.credibility,
                enabled=connector.enabled,
                poll_seconds=connector.poll_seconds
            )

    @classmethod
    def from_config(cls, store, config):
        connectors = [
            UsgsConnector(
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.usgs_enabled
            ),
            EonetConnector(
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.eonet_enabled
            ),
            ReliefWebConnector(
                appname=config.reliefweb_appname,
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.reliefweb_enabled
            ),
            GdacsConnector(
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.gdacs_enabled
            ),
            WhoOutbreakConnector(
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.who_outbreaks_enabled
            ),
            NwsAlertsConnector(
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.nws_alerts_enabled
            ),
            CisaKevConnector(
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.cisa_kev_enabled
            ),
            GitHubAdvisoriesConnector(
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.github_advisories_enabled
            ),
            NoaaSpaceWeatherConnector(
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.noaa_space_weather_enabled
            ),
            FirmsConnector(
                map_key=config.firms_map_key,
                source=config.firms_source,
                days=config.firms_days,
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.firms_enabled
            ),
            WorldBankIndicatorsConnector(
                countries=config.world_bank_countries,
                indicators=config.world_bank_indicators,
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.world_bank_enabled
            ),
            FredConnector(
                api_key=config.fred_api_key,
                series=config.fred_series,
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.fred_enabled
            ),
            GdeltConnector(
                queries=config.gdelt_queries,
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.gdelt_enabled
            ),
            TelegramConnector(
                api_id=config.telegram_api_id,
                api_hash=config.telegram_api_hash,
                session_path=config.telegram_session_path,
                channels=config.telegram_channels,
                messages_per_channel=config.telegram_messages_per_channel,
                deletion_scan_size=config.telegram_deletion_scan_size,
                poll_seconds=config.telegram_poll_seconds,
                timeout=config.request_timeout_seconds,
                enabled=config.telegram_enabled
            ),
            GmailConnector(
                credentials_path=config.gmail_credentials_path,
                token_path=config.gmail_token_path,
                query=config.gmail_query,
                store_body=config.mail_store_body,
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.gmail_enabled
            ),
            OutlookConnector(
                client_id=config.outlook_client_id,
                tenant=config.outlook_tenant,
                token_cache_path=config.outlook_token_cache_path,
                folder=config.outlook_folder,
                store_body=config.mail_store_body,
                timeout=config.request_timeout_seconds,
                max_items=config.max_items_per_source,
                enabled=config.outlook_enabled
            ),
            XConnector(
                bearer_token=config.x_bearer_token,
                usernames=config.x_usernames,
                search_queries=config.x_search_queries,
                poll_seconds=config.x_poll_seconds,
                timeout=config.request_timeout_seconds,
                max_items=config.x_max_results,
                enabled=config.x_enabled
            ),
            PolymarketConnector(
                poll_seconds=config.polymarket_poll_seconds,
                timeout=config.request_timeout_seconds,
                max_items=config.polymarket_max_markets,
                enabled=config.polymarket_enabled
            ),
            *[
                NewsFeedConnector(
                    name=name,
                    feed_url=url,
                    credibility=credibility,
                    poll_seconds=config.news_poll_seconds,
                    timeout=config.request_timeout_seconds,
                    max_items=config.max_items_per_source,
                    enabled=config.news_enabled
                )
                for name, url, credibility in config.news_rss_feeds
            ]
        ]
        reputation = ReputationEngine(
            store,
            enabled=config.reputation_enabled,
            maturity_hours=config.reputation_maturity_hours,
            max_adjustment=config.reputation_max_adjustment,
            prior_strength=config.reputation_prior_strength,
            min_evaluated_outcomes=config.reputation_min_evaluated_outcomes
        )
        embedding_provider = OllamaEmbeddingProvider(
            enabled=config.cluster_embeddings_enabled,
            model=config.cluster_embedding_model,
            timeout=config.request_timeout_seconds
        )
        clusterer = EventClusterer(
            auto_link_threshold=config.cluster_auto_link_threshold,
            review_threshold=config.cluster_review_threshold,
            lookback_days=config.cluster_lookback_days,
            max_candidates=config.cluster_max_candidates,
            embedding_provider=embedding_provider
        )
        understanding = UnderstandingEngine(
            store,
            synthesis_per_cycle=config.worldview_synthesis_per_cycle,
            synthesis_batch_size=config.worldview_batch_size,
            max_candidate_age_days=config.worldview_max_age_days,
            maintenance_enabled=config.worldview_maintenance_enabled,
            clusterer=clusterer,
            prose_claim_extraction_enabled=(
                config.prose_claim_extraction_enabled
            ),
            model_claim_extraction_enabled=(
                config.model_claim_extraction_enabled
            ),
            claim_extraction_max_claims=config.claim_extraction_max_claims,
            epistemic_backfill_enabled=config.epistemic_backfill_enabled,
            epistemic_backfill_batch_size=(
                config.epistemic_backfill_batch_size
            )
        )
        return cls(
            store=store,
            connectors=connectors,
            loop_seconds=config.worker_poll_seconds,
            understanding=understanding,
            reputation=reputation,
            forecast_max_active=config.forecast_max_active,
            forecast_per_cycle=config.forecast_per_cycle,
            analysis_poll_seconds=config.analysis_poll_seconds,
            forecast_poll_seconds=config.forecast_poll_seconds,
            source_backoff_max_seconds=config.source_backoff_max_seconds,
            activity_watchdog_seconds=config.activity_watchdog_seconds
        )

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self):
        if self.running:
            return

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="entity-intelligence-worker",
            daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

        if self._thread:
            self._thread.join(timeout=3)

        self._thread = None

    def run_once(self, force=False):
        now = time.monotonic()
        cycle_started = now
        outcomes = []
        due = [
            connector for connector in self.connectors
            if connector.enabled
            and (force or self.store.source_due(connector.source_id))
            and (force or self._source_ready(connector.source_id, now))
        ]
        activity_started = False
        if due:
            self._emit_activity(
                "intelligence_collecting",
                message=f"Gathering intelligence from {len(due)} source(s)",
                sources=[connector.source_id for connector in due]
            )
            activity_started = True
        for connector in due:
            outcome = self._poll_connector(connector)
            outcomes.append(outcome)
            self._record_source_outcome(connector, outcome, now)

        self.last_analysis_result = AnalysisResult()
        self.last_reputation_result = ReputationResult()
        self.last_forecast_result = {"created": 0, "resolved": 0}
        changed = sum(outcome.result.changed for outcome in outcomes)
        analysis_due = changed or force or now >= self._next_analysis_at
        update_watchdog = None
        try:
            if analysis_due:
                self._emit_activity(
                    "world_model_updating",
                    message=(
                        f"Analyzing {changed} changed document(s) and "
                        "updating the world model"
                    ),
                    changed_documents=changed,
                    watchdog_seconds=self.activity_watchdog_seconds
                )
                activity_started = True
                update_watchdog = self._start_update_watchdog(changed)
                self.last_analysis_result = self.understanding.analyze_pending()
                self._next_analysis_at = now + self.analysis_poll_seconds
        except Exception as exc:
            print("Intelligence understanding cycle failed:", exc)
        finally:
            if update_watchdog:
                update_watchdog.cancel()

        try:
            if force or now >= self._next_forecast_at:
                self.last_forecast_result = self.forecasting.run_cycle()
                self._next_forecast_at = now + self.forecast_poll_seconds
        except Exception as exc:
            print("Intelligence forecasting cycle failed:", exc)

        try:
            if analysis_due:
                self.last_reputation_result = self.reputation.evaluate()
        except Exception as exc:
            print("Intelligence reputation cycle failed:", exc)
        finally:
            if activity_started:
                self._emit_activity(
                    "intelligence_finished",
                    message=self._cycle_message(changed, outcomes),
                    changed_documents=changed,
                    documents_analyzed=(
                        self.last_analysis_result.documents_analyzed
                    ),
                    reputation_outcomes=(
                        self.last_reputation_result.outcomes_recorded
                    ),
                    reputations_updated=(
                        self.last_reputation_result.publishers_updated
                    ),
                    forecasts_created=self.last_forecast_result["created"],
                    forecasts_resolved=self.last_forecast_result["resolved"],
                    errors=sum(bool(outcome.error) for outcome in outcomes),
                    elapsed_seconds=round(time.monotonic() - cycle_started, 1)
                )

        return outcomes

    def _source_ready(self, source_id, now=None):
        now = time.monotonic() if now is None else now
        return now >= self._source_retry_at.get(source_id, 0.0)

    def _record_source_outcome(self, connector, outcome, now=None):
        source_id = connector.source_id
        if not outcome.error:
            self._source_failures.pop(source_id, None)
            self._source_retry_at.pop(source_id, None)
            return

        failures = self._source_failures.get(source_id, 0) + 1
        self._source_failures[source_id] = failures
        base_delay = max(60, int(connector.poll_seconds))
        delay = min(
            self.source_backoff_max_seconds,
            base_delay * (2 ** min(failures - 1, 10))
        )
        now = time.monotonic() if now is None else now
        self._source_retry_at[source_id] = now + delay

    def _cycle_message(self, changed, outcomes):
        errors = sum(bool(outcome.error) for outcome in outcomes)
        analyzed = self.last_analysis_result.documents_analyzed
        calibrated = self.last_reputation_result.publishers_updated
        if errors and not changed:
            return (
                f"Intelligence check completed with {errors} source error(s); "
                "no new evidence was stored"
            )
        if not changed:
            suffix = (
                f"; {calibrated} publisher reputation(s) recalibrated"
                if calibrated else ""
            )
            return "Sources checked; no new or revised evidence" + suffix
        if not analyzed:
            return (
                f"Captured {changed} change(s); no public claims required "
                "world-model updates"
            )
        suffix = (
            f"; recalibrated {calibrated} publisher reputation(s)"
            if calibrated else ""
        )
        return (
            f"Integrated {changed} changed document(s) and analyzed "
            f"{analyzed}{suffix}"
        )

    def _emit_activity(self, state, **details):
        if self.on_activity is None:
            return
        try:
            self.on_activity(state, **details)
        except Exception as exc:
            print("Intelligence activity callback failed:", exc)

    def _start_update_watchdog(self, changed_documents):
        def report_delay():
            self._emit_activity(
                "intelligence_delayed",
                message=(
                    "World-model update is taking longer than expected; "
                    "collection has completed and analysis is continuing"
                ),
                stage="world_model_updating",
                changed_documents=changed_documents,
                elapsed_seconds=self.activity_watchdog_seconds,
                watchdog_seconds=self.activity_watchdog_seconds
            )

        watchdog = threading.Timer(self.activity_watchdog_seconds, report_delay)
        watchdog.daemon = True
        watchdog.start()
        return watchdog

    def _run(self):
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:
                print("Intelligence worker cycle failed:", exc)

            self._stop.wait(self.loop_seconds)

    def _poll_connector(self, connector):
        source_id = connector.source_id
        run_id = self.store.begin_collector_run(source_id)
        cursor = self.store.source_cursor(source_id)

        try:
            batch = connector.poll(cursor)
            result = self.store.ingest_items(source_id, batch.items)
            self.store.finish_collector_run(
                run_id=run_id,
                source_id=source_id,
                cursor=batch.cursor,
                fetched_count=len(batch.items),
                result=result
            )
            return PollOutcome(source_id, len(batch.items), result)
        except Exception as exc:
            self.store.finish_collector_run(
                run_id=run_id,
                source_id=source_id,
                cursor=cursor,
                fetched_count=0,
                error=exc
            )
            return PollOutcome(source_id, 0, IngestResult(), str(exc))
