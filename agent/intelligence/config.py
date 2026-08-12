import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_NEWS_RSS_FEEDS = (
    ("BBC News - World", "https://feeds.bbci.co.uk/news/world/rss.xml", 0.85),
    ("NPR - World", "https://feeds.npr.org/1004/rss.xml", 0.85),
    ("UN News", "https://news.un.org/feed/subscribe/en/news/all/rss.xml", 0.9),
    ("Deutsche Welle - World", "https://rss.dw.com/rdf/rss-en-all", 0.82),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", 0.78),
    ("France 24", "https://www.france24.com/en/rss", 0.8),
    ("The Guardian - World", "https://www.theguardian.com/world/rss", 0.8),
)

DEFAULT_WORLD_BANK_INDICATORS = (
    "FP.CPI.TOTL.ZG",  # Inflation, consumer prices (annual %)
    "NY.GDP.MKTP.KD.ZG",  # GDP growth (annual %)
    "SL.UEM.TOTL.ZS",  # Unemployment, total (% of labor force)
)

DEFAULT_HDX_HAPI_THEMES = (
    "affected-people/humanitarian-needs",
    "coordination-context/operational-presence",
)

DEFAULT_PUBLISHER_PROFILES = ()


@dataclass(frozen=True)
class IntelligenceConfig:
    enabled: bool = False
    database_path: Path = Path("agent/world_intelligence.db")
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8770
    dashboard_enabled: bool = True
    dashboard_open_browser: bool = False
    worker_poll_seconds: int = 30
    activity_watchdog_seconds: int = 90
    analysis_poll_seconds: int = 300
    forecast_poll_seconds: int = 900
    worldview_synthesis_per_cycle: int = 12
    worldview_batch_size: int = 4
    worldview_max_age_days: int = 30
    worldview_maintenance_enabled: bool = True
    prose_claim_extraction_enabled: bool = True
    model_claim_extraction_enabled: bool = False
    claim_extraction_max_claims: int = 20
    claim_grounding_enabled: bool = True
    claim_grounding_batch_size: int = 100
    model_claim_grounding_enabled: bool = False
    epistemic_backfill_enabled: bool = True
    epistemic_backfill_batch_size: int = 50
    belief_revision_enabled: bool = True
    belief_revision_batch_size: int = 50
    verification_execution_enabled: bool = True
    verification_batch_size: int = 20
    verification_max_attempts: int = 8
    verification_remote_per_cycle: int = 3
    topic_reliability_enabled: bool = True
    hypothesis_competition_enabled: bool = True
    hypothesis_batch_size: int = 20
    max_hypotheses_per_situation: int = 5
    model_hypothesis_generation_enabled: bool = False
    intelligence_evaluations_enabled: bool = True
    reasoning_hourly_model_calls: int = 36
    reasoning_daily_model_calls: int = 300
    reasoning_daily_input_tokens: int = 1_000_000
    reasoning_daily_output_tokens: int = 250_000
    reasoning_job_lease_seconds: int = 120
    reasoning_forecast_hourly_reserve: int = 2
    reasoning_forecast_daily_reserve: int = 12
    reasoning_forecast_hourly_calls: int = 4
    reasoning_forecast_daily_calls: int = 30
    reasoning_grounding_hourly_reserve: int = 4
    reasoning_grounding_daily_reserve: int = 40
    reasoning_grounding_hourly_calls: int = 8
    reasoning_grounding_daily_calls: int = 60
    reasoning_worldview_hourly_calls: int = 4
    reasoning_worldview_daily_calls: int = 20
    reasoning_article_hourly_reserve: int = 2
    reasoning_article_daily_reserve: int = 30
    reasoning_article_hourly_calls: int = 8
    reasoning_article_daily_calls: int = 100
    reasoning_article_fresh_hourly_reserve: int = 2
    reasoning_article_fresh_daily_reserve: int = 12
    reasoning_article_fresh_hourly_calls: int = 4
    reasoning_article_fresh_daily_calls: int = 40
    reasoning_comparison_hourly_reserve: int = 1
    reasoning_comparison_daily_reserve: int = 15
    reasoning_comparison_hourly_calls: int = 4
    reasoning_comparison_daily_calls: int = 40
    active_acquisition_enabled: bool = False
    active_acquisition_per_cycle: int = 5
    cluster_auto_link_threshold: float = 0.82
    cluster_review_threshold: float = 0.65
    cluster_lookback_days: int = 14
    cluster_max_candidates: int = 200
    cluster_embeddings_enabled: bool = False
    cluster_embedding_model: str = ""
    source_backoff_max_seconds: int = 21600
    request_timeout_seconds: int = 15
    max_items_per_source: int = 50
    reputation_enabled: bool = True
    reputation_maturity_hours: float = 6.0
    reputation_max_adjustment: float = 0.15
    reputation_prior_strength: float = 8.0
    reputation_min_evaluated_outcomes: int = 12
    publisher_profiles: tuple[tuple[str, float, float, str, str], ...] = (
        DEFAULT_PUBLISHER_PROFILES
    )
    forecast_max_active: int = 12
    forecast_per_cycle: int = 2
    forecast_resolution_per_cycle: int = 4
    forecast_v2_mode: str = "shadow"
    ensemble_training_enabled: bool = True
    ensemble_min_training_samples: int = 100
    ensemble_min_validation_samples: int = 30
    learned_ensemble_mode: str = "shadow"
    reliefweb_appname: str = ""
    reliefweb_enabled: bool = True
    acled_enabled: bool = False
    acled_username: str = ""
    acled_password: str = ""
    acled_lookback_days: int = 7
    hdx_hapi_enabled: bool = False
    hdx_hapi_app_identifier: str = ""
    hdx_hapi_locations: tuple[str, ...] = ()
    hdx_hapi_themes: tuple[str, ...] = DEFAULT_HDX_HAPI_THEMES
    copernicus_ems_enabled: bool = True
    usgs_enabled: bool = True
    eonet_enabled: bool = True
    gdacs_enabled: bool = True
    who_outbreaks_enabled: bool = True
    nws_alerts_enabled: bool = True
    cisa_kev_enabled: bool = True
    github_advisories_enabled: bool = True
    noaa_space_weather_enabled: bool = True
    firms_enabled: bool = False
    firms_map_key: str = ""
    firms_source: str = "VIIRS_SNPP_NRT"
    firms_days: int = 1
    aircraft_enabled: bool = False
    aircraft_center: str = ""
    aircraft_radius_nm: int = 100
    aircraft_poll_seconds: int = 120
    aircraft_max_states: int = 300
    geography_backfill_batch_size: int = 50
    location_inference_enabled: bool = True
    location_model_inference_enabled: bool = False
    location_geocoding_enabled: bool = True
    location_inference_batch_size: int = 25
    location_model_calls_per_cycle: int = 1
    location_inference_poll_seconds: int = 300
    open_source_enrichment_enabled: bool = True
    open_source_enrichment_batch_size: int = 50
    open_source_model_enrichment_enabled: bool = True
    open_source_model_calls_per_cycle: int = 1
    open_source_model_reports_per_call: int = 5
    open_source_enrichment_poll_seconds: int = 300
    article_acquisition_enabled: bool = True
    article_acquisition_batch_size: int = 5
    article_acquisition_poll_seconds: int = 600
    article_acquisition_event_ready_per_cycle: int = 2
    article_acquisition_max_active_per_publisher: int = 25
    article_acquisition_max_active_global: int = 100
    article_fresh_window_minutes: int = 30
    article_fresh_max_active_per_publisher: int = 2
    article_fresh_max_active_global: int = 10
    workload_health_window_minutes: int = 60
    intelligence_disk_soft_limit_bytes: int = 2_147_483_648
    intelligence_disk_hard_limit_bytes: int = 3_221_225_472
    intelligence_replay_max_items: int = 2_000
    intelligence_replay_max_bytes: int = 100_000_000
    intelligence_replay_batch_size: int = 100
    intelligence_replay_max_passes: int = 50
    semantic_framing_enabled: bool = True
    semantic_framing_batch_size: int = 5
    semantic_framing_model_calls_per_cycle: int = 4
    semantic_framing_poll_seconds: int = 600
    semantic_framing_event_ready_per_cycle: int = 2
    event_framing_comparison_enabled: bool = True
    event_framing_comparison_batch_size: int = 20
    geospatial_features_enabled: bool = True
    geospatial_feature_batch_size: int = 100
    environment_layers_enabled: bool = True
    environment_layer_batch_size: int = 100
    global_weather_enabled: bool = False
    global_weather_grid_degrees: float = 30.0
    global_weather_horizon_hours: int = 24
    global_weather_max_cells: int = 200
    global_weather_batch_cells: int = 25
    global_weather_poll_seconds: int = 21600
    ourairports_enabled: bool = True
    ourairports_types: tuple[str, ...] = ("large_airport", "medium_airport")
    ourairports_max_assets: int = 10000
    ourairports_poll_seconds: int = 86400
    nga_wpi_enabled: bool = True
    nga_wpi_max_assets: int = 5000
    nga_wpi_poll_seconds: int = 604800
    world_graph_enabled: bool = True
    world_graph_batch_size: int = 100
    world_graph_comparison_ready_per_cycle: int = 20
    event_fusion_enabled: bool = True
    event_fusion_batch_size: int = 100
    event_fusion_comparison_ready_per_cycle: int = 20
    event_fusion_recent_per_cycle: int = 20
    event_fusion_auto_link_threshold: float = 0.82
    event_fusion_review_threshold: float = 0.65
    event_fusion_max_candidates: int = 100
    event_fusion_lookback_days: int = 14
    event_assessment_enabled: bool = True
    event_assessment_batch_size: int = 100
    world_bank_enabled: bool = True
    world_bank_countries: tuple[str, ...] = ("WLD",)
    world_bank_indicators: tuple[str, ...] = DEFAULT_WORLD_BANK_INDICATORS
    fred_enabled: bool = False
    fred_api_key: str = ""
    fred_series: tuple[str, ...] = ()
    gdelt_enabled: bool = False
    gdelt_queries: tuple[str, ...] = ()
    telegram_enabled: bool = False
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    telegram_session_path: Path = Path("agent/private/telegram_entity")
    telegram_channels: tuple[str, ...] = ()
    telegram_poll_seconds: int = 120
    telegram_messages_per_channel: int = 50
    telegram_deletion_scan_size: int = 100
    telegram_media_enabled: bool = False
    telegram_media_directory: Path = Path("agent/private/intelligence_media")
    telegram_media_max_bytes: int = 10_000_000
    telegram_media_max_per_cycle: int = 3
    telegram_media_whisper_model: Path | None = None
    telegram_media_retention_hours: int = 168
    gmail_enabled: bool = False
    gmail_credentials_path: Path = Path("agent/google_gmail_credentials.json")
    gmail_token_path: Path = Path("agent/google_gmail_token.json")
    gmail_query: str = "newer_than:7d -in:spam -in:trash"
    outlook_enabled: bool = False
    outlook_client_id: str = ""
    outlook_tenant: str = "common"
    outlook_token_cache_path: Path = Path("agent/outlook_mail_token_cache.json")
    outlook_folder: str = "inbox"
    mail_store_body: bool = False
    x_enabled: bool = False
    x_bearer_token: str = ""
    x_usernames: tuple[str, ...] = ()
    x_search_queries: tuple[str, ...] = ()
    x_poll_seconds: int = 900
    x_max_results: int = 25
    news_enabled: bool = True
    news_rss_feeds: tuple[tuple, ...] = DEFAULT_NEWS_RSS_FEEDS
    news_poll_seconds: int = 300
    news_article_requests_per_cycle: int = 2
    polymarket_enabled: bool = True
    polymarket_poll_seconds: int = 300
    polymarket_max_markets: int = 50

    @classmethod
    def from_env(cls):
        return cls(
            enabled=_env_bool("ENTITY_INTELLIGENCE_ENABLED", False),
            database_path=Path(
                os.getenv(
                    "ENTITY_INTELLIGENCE_DB",
                    "agent/world_intelligence.db"
                )
            ),
            dashboard_host=os.getenv(
                "ENTITY_INTELLIGENCE_DASHBOARD_HOST",
                "127.0.0.1"
            ).strip() or "127.0.0.1",
            dashboard_port=_env_int(
                "ENTITY_INTELLIGENCE_DASHBOARD_PORT",
                8770,
                minimum=0
            ),
            dashboard_enabled=_env_bool(
                "ENTITY_INTELLIGENCE_DASHBOARD_ENABLED",
                True
            ),
            dashboard_open_browser=_env_bool(
                "ENTITY_INTELLIGENCE_DASHBOARD_OPEN_BROWSER",
                False
            ),
            worker_poll_seconds=_env_int(
                "ENTITY_INTELLIGENCE_WORKER_POLL_SECONDS",
                30,
                minimum=5
            ),
            activity_watchdog_seconds=_env_int(
                "ENTITY_INTELLIGENCE_ACTIVITY_WATCHDOG_SECONDS",
                90,
                minimum=15, maximum=900
            ),
            analysis_poll_seconds=_env_int(
                "ENTITY_INTELLIGENCE_ANALYSIS_POLL_SECONDS",
                300,
                minimum=30
            ),
            forecast_poll_seconds=_env_int(
                "ENTITY_INTELLIGENCE_FORECAST_POLL_SECONDS",
                900,
                minimum=60
            ),
            worldview_synthesis_per_cycle=_env_int(
                "ENTITY_WORLDVIEW_SYNTHESIS_PER_CYCLE", 12,
                minimum=1, maximum=50
            ),
            worldview_batch_size=_env_int(
                "ENTITY_WORLDVIEW_BATCH_SIZE", 4,
                minimum=1, maximum=10
            ),
            worldview_max_age_days=_env_int(
                "ENTITY_WORLDVIEW_MAX_AGE_DAYS", 30,
                minimum=1, maximum=365
            ),
            worldview_maintenance_enabled=_env_bool(
                "ENTITY_WORLDVIEW_MAINTENANCE_ENABLED", True
            ),
            prose_claim_extraction_enabled=_env_bool(
                "ENTITY_PROSE_CLAIM_EXTRACTION_ENABLED", True
            ),
            model_claim_extraction_enabled=_env_bool(
                "ENTITY_MODEL_CLAIM_EXTRACTION_ENABLED", False
            ),
            claim_extraction_max_claims=_env_int(
                "ENTITY_CLAIM_EXTRACTION_MAX_CLAIMS", 20,
                minimum=2, maximum=50
            ),
            claim_grounding_enabled=_env_bool(
                "ENTITY_CLAIM_GROUNDING_ENABLED", True
            ),
            claim_grounding_batch_size=_env_int(
                "ENTITY_CLAIM_GROUNDING_BATCH_SIZE", 100,
                minimum=1, maximum=500
            ),
            model_claim_grounding_enabled=_env_bool(
                "ENTITY_MODEL_CLAIM_GROUNDING_ENABLED", False
            ),
            epistemic_backfill_enabled=_env_bool(
                "ENTITY_EPISTEMIC_BACKFILL_ENABLED", True
            ),
            epistemic_backfill_batch_size=_env_int(
                "ENTITY_EPISTEMIC_BACKFILL_BATCH_SIZE", 50,
                minimum=1, maximum=100
            ),
            belief_revision_enabled=_env_bool(
                "ENTITY_BELIEF_REVISION_ENABLED", True
            ),
            belief_revision_batch_size=_env_int(
                "ENTITY_BELIEF_REVISION_BATCH_SIZE", 50,
                minimum=1, maximum=200
            ),
            verification_execution_enabled=_env_bool(
                "ENTITY_VERIFICATION_EXECUTION_ENABLED", True
            ),
            verification_batch_size=_env_int(
                "ENTITY_VERIFICATION_BATCH_SIZE", 20,
                minimum=1, maximum=100
            ),
            verification_max_attempts=_env_int(
                "ENTITY_VERIFICATION_MAX_ATTEMPTS", 8,
                minimum=1, maximum=20
            ),
            verification_remote_per_cycle=_env_int(
                "ENTITY_VERIFICATION_REMOTE_PER_CYCLE", 3,
                minimum=0, maximum=10
            ),
            topic_reliability_enabled=_env_bool(
                "ENTITY_TOPIC_RELIABILITY_ENABLED", True
            ),
            hypothesis_competition_enabled=_env_bool(
                "ENTITY_HYPOTHESIS_COMPETITION_ENABLED", True
            ),
            hypothesis_batch_size=_env_int(
                "ENTITY_HYPOTHESIS_BATCH_SIZE", 20, minimum=1, maximum=100
            ),
            max_hypotheses_per_situation=_env_int(
                "ENTITY_MAX_HYPOTHESES_PER_SITUATION", 5,
                minimum=3, maximum=8
            ),
            model_hypothesis_generation_enabled=_env_bool(
                "ENTITY_MODEL_HYPOTHESIS_GENERATION_ENABLED", False
            ),
            intelligence_evaluations_enabled=_env_bool(
                "ENTITY_INTELLIGENCE_EVALUATIONS_ENABLED", True
            ),
            reasoning_hourly_model_calls=_env_int(
                "ENTITY_REASONING_HOURLY_MODEL_CALLS",36,minimum=1,maximum=1000
            ),
            reasoning_daily_model_calls=_env_int(
                "ENTITY_REASONING_DAILY_MODEL_CALLS",300,minimum=1,maximum=10000
            ),
            reasoning_daily_input_tokens=_env_int(
                "ENTITY_REASONING_DAILY_INPUT_TOKENS",1_000_000,
                minimum=10_000,maximum=100_000_000
            ),
            reasoning_daily_output_tokens=_env_int(
                "ENTITY_REASONING_DAILY_OUTPUT_TOKENS",250_000,
                minimum=10_000,maximum=20_000_000
            ),
            reasoning_job_lease_seconds=_env_int(
                "ENTITY_REASONING_JOB_LEASE_SECONDS",120,minimum=30,maximum=900
            ),
            reasoning_forecast_hourly_reserve=_env_int(
                "ENTITY_REASONING_FORECAST_HOURLY_RESERVE",2,
                minimum=0,maximum=100
            ),
            reasoning_forecast_daily_reserve=_env_int(
                "ENTITY_REASONING_FORECAST_DAILY_RESERVE",12,
                minimum=0,maximum=1000
            ),
            reasoning_forecast_hourly_calls=_env_int(
                "ENTITY_REASONING_FORECAST_HOURLY_CALLS",4,
                minimum=1,maximum=100
            ),
            reasoning_forecast_daily_calls=_env_int(
                "ENTITY_REASONING_FORECAST_DAILY_CALLS",30,
                minimum=1,maximum=1000
            ),
            reasoning_grounding_hourly_reserve=_env_int(
                "ENTITY_REASONING_GROUNDING_HOURLY_RESERVE",4,
                minimum=0,maximum=100
            ),
            reasoning_grounding_daily_reserve=_env_int(
                "ENTITY_REASONING_GROUNDING_DAILY_RESERVE",40,
                minimum=0,maximum=1000
            ),
            reasoning_grounding_hourly_calls=_env_int(
                "ENTITY_REASONING_GROUNDING_HOURLY_CALLS",8,
                minimum=1,maximum=100
            ),
            reasoning_grounding_daily_calls=_env_int(
                "ENTITY_REASONING_GROUNDING_DAILY_CALLS",60,
                minimum=1,maximum=1000
            ),
            reasoning_worldview_hourly_calls=_env_int(
                "ENTITY_REASONING_WORLDVIEW_HOURLY_CALLS",4,
                minimum=1,maximum=100
            ),
            reasoning_worldview_daily_calls=_env_int(
                "ENTITY_REASONING_WORLDVIEW_DAILY_CALLS",20,
                minimum=1,maximum=1000
            ),
            reasoning_article_hourly_reserve=_env_int(
                "ENTITY_REASONING_ARTICLE_HOURLY_RESERVE",2,minimum=0,maximum=100
            ),
            reasoning_article_daily_reserve=_env_int(
                "ENTITY_REASONING_ARTICLE_DAILY_RESERVE",30,minimum=0,maximum=1000
            ),
            reasoning_article_hourly_calls=_env_int(
                "ENTITY_REASONING_ARTICLE_HOURLY_CALLS",8,minimum=1,maximum=100
            ),
            reasoning_article_daily_calls=_env_int(
                "ENTITY_REASONING_ARTICLE_DAILY_CALLS",100,minimum=1,maximum=1000
            ),
            reasoning_article_fresh_hourly_reserve=_env_int(
                "ENTITY_REASONING_ARTICLE_FRESH_HOURLY_RESERVE",2,
                minimum=0,maximum=100
            ),
            reasoning_article_fresh_daily_reserve=_env_int(
                "ENTITY_REASONING_ARTICLE_FRESH_DAILY_RESERVE",12,
                minimum=0,maximum=1000
            ),
            reasoning_article_fresh_hourly_calls=_env_int(
                "ENTITY_REASONING_ARTICLE_FRESH_HOURLY_CALLS",4,
                minimum=1,maximum=100
            ),
            reasoning_article_fresh_daily_calls=_env_int(
                "ENTITY_REASONING_ARTICLE_FRESH_DAILY_CALLS",40,
                minimum=1,maximum=1000
            ),
            reasoning_comparison_hourly_reserve=_env_int(
                "ENTITY_REASONING_COMPARISON_HOURLY_RESERVE",1,
                minimum=0,maximum=100
            ),
            reasoning_comparison_daily_reserve=_env_int(
                "ENTITY_REASONING_COMPARISON_DAILY_RESERVE",15,
                minimum=0,maximum=1000
            ),
            reasoning_comparison_hourly_calls=_env_int(
                "ENTITY_REASONING_COMPARISON_HOURLY_CALLS",4,
                minimum=1,maximum=100
            ),
            reasoning_comparison_daily_calls=_env_int(
                "ENTITY_REASONING_COMPARISON_DAILY_CALLS",40,
                minimum=1,maximum=1000
            ),
            active_acquisition_enabled=_env_bool(
                "ENTITY_ACTIVE_ACQUISITION_ENABLED",False
            ),
            active_acquisition_per_cycle=_env_int(
                "ENTITY_ACTIVE_ACQUISITION_PER_CYCLE",5,minimum=1,maximum=20
            ),
            cluster_auto_link_threshold=_env_float(
                "ENTITY_CLUSTER_AUTO_LINK_THRESHOLD", 0.82,
                minimum=0.5, maximum=0.99
            ),
            cluster_review_threshold=_env_float(
                "ENTITY_CLUSTER_REVIEW_THRESHOLD", 0.65,
                minimum=0.3, maximum=0.95
            ),
            cluster_lookback_days=_env_int(
                "ENTITY_CLUSTER_LOOKBACK_DAYS", 14,
                minimum=1, maximum=90
            ),
            cluster_max_candidates=_env_int(
                "ENTITY_CLUSTER_MAX_CANDIDATES", 200,
                minimum=10, maximum=1000
            ),
            cluster_embeddings_enabled=_env_bool(
                "ENTITY_CLUSTER_LOCAL_EMBEDDINGS", False
            ),
            cluster_embedding_model=os.getenv(
                "ENTITY_CLUSTER_EMBEDDING_MODEL", ""
            ).strip(),
            source_backoff_max_seconds=_env_int(
                "ENTITY_INTELLIGENCE_SOURCE_BACKOFF_MAX_SECONDS",
                21600,
                minimum=60
            ),
            request_timeout_seconds=_env_int(
                "ENTITY_INTELLIGENCE_REQUEST_TIMEOUT_SECONDS",
                15,
                minimum=1
            ),
            max_items_per_source=_env_int(
                "ENTITY_INTELLIGENCE_MAX_ITEMS_PER_SOURCE",
                50,
                minimum=1
            ),
            reputation_enabled=_env_bool(
                "ENTITY_REPUTATION_ENABLED", True
            ),
            reputation_maturity_hours=_env_float(
                "ENTITY_REPUTATION_MATURITY_HOURS", 6.0, minimum=0.0
            ),
            reputation_max_adjustment=_env_float(
                "ENTITY_REPUTATION_MAX_ADJUSTMENT", 0.15,
                minimum=0.0, maximum=0.3
            ),
            reputation_prior_strength=_env_float(
                "ENTITY_REPUTATION_PRIOR_STRENGTH", 8.0,
                minimum=2.0, maximum=100.0
            ),
            reputation_min_evaluated_outcomes=_env_int(
                "ENTITY_REPUTATION_MIN_EVALUATED_OUTCOMES", 12,
                minimum=3, maximum=100
            ),
            publisher_profiles=_env_publisher_profiles(
                os.getenv("ENTITY_PUBLISHER_PROFILES")
            ),
            forecast_max_active=_env_int(
                "ENTITY_FORECAST_MAX_ACTIVE", 12, minimum=1
            ),
            forecast_per_cycle=_env_int(
                "ENTITY_FORECAST_PER_CYCLE", 2, minimum=1
            ),
            forecast_resolution_per_cycle=_env_int(
                "ENTITY_FORECAST_RESOLUTION_PER_CYCLE", 4,
                minimum=1, maximum=50
            ),
            forecast_v2_mode=os.getenv(
                "ENTITY_FORECAST_V2_MODE", "shadow"
            ).strip().lower() or "shadow",
            ensemble_training_enabled=_env_bool(
                "ENTITY_ENSEMBLE_TRAINING_ENABLED", True
            ),
            ensemble_min_training_samples=_env_int(
                "ENTITY_ENSEMBLE_MIN_TRAINING_SAMPLES", 100,
                minimum=50, maximum=10000
            ),
            ensemble_min_validation_samples=_env_int(
                "ENTITY_ENSEMBLE_MIN_VALIDATION_SAMPLES", 30,
                minimum=20, maximum=5000
            ),
            learned_ensemble_mode=os.getenv(
                "ENTITY_LEARNED_ENSEMBLE_MODE", "shadow"
            ).strip().lower() or "shadow",
            reliefweb_appname=os.getenv(
                "ENTITY_RELIEFWEB_APPNAME",
                ""
            ).strip(),
            reliefweb_enabled=_env_bool(
                "ENTITY_RELIEFWEB_ENABLED",
                True
            ),
            acled_enabled=_env_bool("ENTITY_ACLED_ENABLED", False),
            acled_username=os.getenv("ENTITY_ACLED_USERNAME", "").strip(),
            acled_password=os.getenv("ENTITY_ACLED_PASSWORD", ""),
            acled_lookback_days=_env_int("ENTITY_ACLED_LOOKBACK_DAYS", 7, minimum=1, maximum=30),
            hdx_hapi_enabled=_env_bool("ENTITY_HDX_HAPI_ENABLED", False),
            hdx_hapi_app_identifier=os.getenv("ENTITY_HDX_HAPI_APP_IDENTIFIER", "").strip(),
            hdx_hapi_locations=_env_csv(os.getenv("ENTITY_HDX_HAPI_LOCATIONS"), ()),
            hdx_hapi_themes=_env_csv(os.getenv("ENTITY_HDX_HAPI_THEMES"), DEFAULT_HDX_HAPI_THEMES),
            copernicus_ems_enabled=_env_bool("ENTITY_COPERNICUS_EMS_ENABLED", True),
            usgs_enabled=_env_bool("ENTITY_USGS_ENABLED", True),
            eonet_enabled=_env_bool("ENTITY_EONET_ENABLED", True),
            gdacs_enabled=_env_bool("ENTITY_GDACS_ENABLED", True),
            who_outbreaks_enabled=_env_bool(
                "ENTITY_WHO_OUTBREAKS_ENABLED", True
            ),
            nws_alerts_enabled=_env_bool("ENTITY_NWS_ALERTS_ENABLED", True),
            cisa_kev_enabled=_env_bool("ENTITY_CISA_KEV_ENABLED", True),
            github_advisories_enabled=_env_bool(
                "ENTITY_GITHUB_ADVISORIES_ENABLED", True
            ),
            noaa_space_weather_enabled=_env_bool(
                "ENTITY_NOAA_SPACE_WEATHER_ENABLED", True
            ),
            firms_enabled=_env_bool("ENTITY_FIRMS_ENABLED", False),
            firms_map_key=os.getenv("ENTITY_FIRMS_MAP_KEY", "").strip(),
            firms_source=os.getenv(
                "ENTITY_FIRMS_SOURCE", "VIIRS_SNPP_NRT"
            ).strip() or "VIIRS_SNPP_NRT",
            firms_days=_env_int("ENTITY_FIRMS_DAYS", 1, minimum=1),
            aircraft_enabled=_env_bool("ENTITY_AIRCRAFT_ENABLED", False),
            aircraft_center=os.getenv("ENTITY_AIRCRAFT_CENTER", "").strip(),
            aircraft_radius_nm=_env_int("ENTITY_AIRCRAFT_RADIUS_NM", 100, minimum=1, maximum=250),
            aircraft_poll_seconds=_env_int("ENTITY_AIRCRAFT_POLL_SECONDS", 120, minimum=60),
            aircraft_max_states=_env_int("ENTITY_AIRCRAFT_MAX_STATES", 300, minimum=1, maximum=1000),
            geography_backfill_batch_size=_env_int("ENTITY_GEOGRAPHY_BACKFILL_BATCH_SIZE", 50, minimum=1, maximum=500),
            location_inference_enabled=_env_bool(
                "ENTITY_LOCATION_INFERENCE_ENABLED", True
            ),
            location_model_inference_enabled=_env_bool(
                "ENTITY_LOCATION_MODEL_INFERENCE_ENABLED", False
            ),
            location_geocoding_enabled=_env_bool(
                "ENTITY_LOCATION_GEOCODING_ENABLED", True
            ),
            location_inference_batch_size=_env_int(
                "ENTITY_LOCATION_INFERENCE_BATCH_SIZE", 25,
                minimum=1, maximum=200
            ),
            location_model_calls_per_cycle=_env_int(
                "ENTITY_LOCATION_MODEL_CALLS_PER_CYCLE", 1,
                minimum=0, maximum=25
            ),
            location_inference_poll_seconds=_env_int(
                "ENTITY_LOCATION_INFERENCE_POLL_SECONDS", 300,
                minimum=30, maximum=86400
            ),
            open_source_enrichment_enabled=_env_bool(
                "ENTITY_OPEN_SOURCE_ENRICHMENT_ENABLED", True
            ),
            open_source_enrichment_batch_size=_env_int(
                "ENTITY_OPEN_SOURCE_ENRICHMENT_BATCH_SIZE", 50,
                minimum=1, maximum=500
            ),
            open_source_model_enrichment_enabled=_env_bool(
                "ENTITY_OPEN_SOURCE_MODEL_ENRICHMENT_ENABLED", True
            ),
            open_source_model_calls_per_cycle=_env_int(
                "ENTITY_OPEN_SOURCE_MODEL_CALLS_PER_CYCLE", 1,
                minimum=0, maximum=25
            ),
            open_source_model_reports_per_call=_env_int(
                "ENTITY_OPEN_SOURCE_MODEL_REPORTS_PER_CALL", 5,
                minimum=1, maximum=10
            ),
            open_source_enrichment_poll_seconds=_env_int(
                "ENTITY_OPEN_SOURCE_ENRICHMENT_POLL_SECONDS", 300,
                minimum=30, maximum=86400
            ),
            article_acquisition_enabled=_env_bool(
                "ENTITY_ARTICLE_ACQUISITION_ENABLED", True
            ),
            article_acquisition_batch_size=_env_int(
                "ENTITY_ARTICLE_ACQUISITION_BATCH_SIZE", 5,
                minimum=1, maximum=25
            ),
            article_acquisition_poll_seconds=_env_int(
                "ENTITY_ARTICLE_ACQUISITION_POLL_SECONDS", 600,
                minimum=60, maximum=86400
            ),
            article_acquisition_event_ready_per_cycle=_env_int(
                "ENTITY_ARTICLE_ACQUISITION_EVENT_READY_PER_CYCLE", 2,
                minimum=0, maximum=25
            ),
            article_acquisition_max_active_per_publisher=_env_int(
                "ENTITY_ARTICLE_ACQUISITION_MAX_ACTIVE_PER_PUBLISHER", 25,
                minimum=1, maximum=10000
            ),
            article_acquisition_max_active_global=_env_int(
                "ENTITY_ARTICLE_ACQUISITION_MAX_ACTIVE_GLOBAL", 100,
                minimum=1, maximum=100000
            ),
            article_fresh_window_minutes=_env_int(
                "ENTITY_ARTICLE_FRESH_WINDOW_MINUTES", 30,
                minimum=5, maximum=1440
            ),
            article_fresh_max_active_per_publisher=_env_int(
                "ENTITY_ARTICLE_FRESH_MAX_ACTIVE_PER_PUBLISHER", 2,
                minimum=1, maximum=100
            ),
            article_fresh_max_active_global=_env_int(
                "ENTITY_ARTICLE_FRESH_MAX_ACTIVE_GLOBAL", 10,
                minimum=1, maximum=1000
            ),
            workload_health_window_minutes=_env_int(
                "ENTITY_WORKLOAD_HEALTH_WINDOW_MINUTES", 60,
                minimum=15, maximum=1440
            ),
            intelligence_disk_soft_limit_bytes=_env_disk_limits()[0],
            intelligence_disk_hard_limit_bytes=_env_disk_limits()[1],
            intelligence_replay_max_items=_env_int(
                "ENTITY_INTELLIGENCE_REPLAY_MAX_ITEMS", 2000,
                minimum=1, maximum=10000
            ),
            intelligence_replay_max_bytes=_env_int(
                "ENTITY_INTELLIGENCE_REPLAY_MAX_BYTES", 100_000_000,
                minimum=1_000_000, maximum=1_000_000_000
            ),
            intelligence_replay_batch_size=_env_int(
                "ENTITY_INTELLIGENCE_REPLAY_BATCH_SIZE", 100,
                minimum=1, maximum=500
            ),
            intelligence_replay_max_passes=_env_int(
                "ENTITY_INTELLIGENCE_REPLAY_MAX_PASSES", 50,
                minimum=1, maximum=500
            ),
            semantic_framing_enabled=_env_bool(
                "ENTITY_SEMANTIC_FRAMING_ENABLED", True
            ),
            semantic_framing_batch_size=_env_int(
                "ENTITY_SEMANTIC_FRAMING_BATCH_SIZE", 5,
                minimum=1, maximum=25
            ),
            semantic_framing_model_calls_per_cycle=_env_int(
                "ENTITY_SEMANTIC_FRAMING_MODEL_CALLS_PER_CYCLE", 4,
                minimum=0, maximum=10
            ),
            semantic_framing_poll_seconds=_env_int(
                "ENTITY_SEMANTIC_FRAMING_POLL_SECONDS", 600,
                minimum=60, maximum=86400
            ),
            semantic_framing_event_ready_per_cycle=_env_int(
                "ENTITY_SEMANTIC_FRAMING_EVENT_READY_PER_CYCLE", 2,
                minimum=0, maximum=25
            ),
            event_framing_comparison_enabled=_env_bool(
                "ENTITY_EVENT_FRAMING_COMPARISON_ENABLED", True
            ),
            event_framing_comparison_batch_size=_env_int(
                "ENTITY_EVENT_FRAMING_COMPARISON_BATCH_SIZE", 20,
                minimum=1, maximum=100
            ),
            geospatial_features_enabled=_env_bool("ENTITY_GEOSPATIAL_FEATURES_ENABLED", True),
            geospatial_feature_batch_size=_env_int("ENTITY_GEOSPATIAL_FEATURE_BATCH_SIZE", 100, minimum=1, maximum=500),
            environment_layers_enabled=_env_bool(
                "ENTITY_ENVIRONMENT_LAYERS_ENABLED", True
            ),
            environment_layer_batch_size=_env_int(
                "ENTITY_ENVIRONMENT_LAYER_BATCH_SIZE", 100,
                minimum=1, maximum=500
            ),
            global_weather_enabled=_env_bool(
                "ENTITY_GLOBAL_WEATHER_ENABLED", False
            ),
            global_weather_grid_degrees=_env_float(
                "ENTITY_GLOBAL_WEATHER_GRID_DEGREES", 30.0,
                minimum=5.0, maximum=90.0
            ),
            global_weather_horizon_hours=_env_int(
                "ENTITY_GLOBAL_WEATHER_HORIZON_HOURS", 24,
                minimum=6, maximum=168
            ),
            global_weather_max_cells=_env_int(
                "ENTITY_GLOBAL_WEATHER_MAX_CELLS", 200,
                minimum=1, maximum=2000
            ),
            global_weather_batch_cells=_env_int(
                "ENTITY_GLOBAL_WEATHER_BATCH_CELLS", 25,
                minimum=1, maximum=50
            ),
            global_weather_poll_seconds=_env_int(
                "ENTITY_GLOBAL_WEATHER_POLL_SECONDS", 21600,
                minimum=3600
            ),
            ourairports_enabled=_env_bool("ENTITY_OURAIRPORTS_ENABLED", True),
            ourairports_types=_env_csv(
                os.getenv("ENTITY_OURAIRPORTS_TYPES"),
                ("large_airport", "medium_airport")
            ),
            ourairports_max_assets=_env_int(
                "ENTITY_OURAIRPORTS_MAX_ASSETS", 10000,
                minimum=1, maximum=25000
            ),
            ourairports_poll_seconds=_env_int(
                "ENTITY_OURAIRPORTS_POLL_SECONDS", 86400,
                minimum=3600
            ),
            nga_wpi_enabled=_env_bool("ENTITY_NGA_WPI_ENABLED", True),
            nga_wpi_max_assets=_env_int(
                "ENTITY_NGA_WPI_MAX_ASSETS", 5000,
                minimum=1, maximum=10000
            ),
            nga_wpi_poll_seconds=_env_int(
                "ENTITY_NGA_WPI_POLL_SECONDS", 604800,
                minimum=86400
            ),
            world_graph_enabled=_env_bool("ENTITY_WORLD_GRAPH_ENABLED", True),
            world_graph_batch_size=_env_int("ENTITY_WORLD_GRAPH_BATCH_SIZE", 100, minimum=2, maximum=500),
            world_graph_comparison_ready_per_cycle=_env_int(
                "ENTITY_WORLD_GRAPH_COMPARISON_READY_PER_CYCLE", 20,
                minimum=0, maximum=500
            ),
            event_fusion_enabled=_env_bool("ENTITY_EVENT_FUSION_ENABLED", True),
            event_fusion_batch_size=_env_int(
                "ENTITY_EVENT_FUSION_BATCH_SIZE", 100, minimum=1, maximum=500
            ),
            event_fusion_comparison_ready_per_cycle=_env_int(
                "ENTITY_EVENT_FUSION_COMPARISON_READY_PER_CYCLE", 20,
                minimum=0, maximum=500
            ),
            event_fusion_recent_per_cycle=_env_int(
                "ENTITY_EVENT_FUSION_RECENT_PER_CYCLE", 20,
                minimum=0, maximum=500
            ),
            event_fusion_auto_link_threshold=_env_float(
                "ENTITY_EVENT_FUSION_AUTO_LINK_THRESHOLD", .82,
                minimum=.55, maximum=.99
            ),
            event_fusion_review_threshold=_env_float(
                "ENTITY_EVENT_FUSION_REVIEW_THRESHOLD", .65,
                minimum=.3, maximum=.99
            ),
            event_fusion_max_candidates=_env_int(
                "ENTITY_EVENT_FUSION_MAX_CANDIDATES", 100,
                minimum=5, maximum=500
            ),
            event_fusion_lookback_days=_env_int(
                "ENTITY_EVENT_FUSION_LOOKBACK_DAYS", 14,
                minimum=1, maximum=90
            ),
            event_assessment_enabled=_env_bool(
                "ENTITY_EVENT_ASSESSMENT_ENABLED", True
            ),
            event_assessment_batch_size=_env_int(
                "ENTITY_EVENT_ASSESSMENT_BATCH_SIZE", 100,
                minimum=1, maximum=500
            ),
            world_bank_enabled=_env_bool("ENTITY_WORLD_BANK_ENABLED", True),
            world_bank_countries=_env_csv(
                os.getenv("ENTITY_WORLD_BANK_COUNTRIES"), ("WLD",)
            ),
            world_bank_indicators=_env_csv(
                os.getenv("ENTITY_WORLD_BANK_INDICATORS"),
                DEFAULT_WORLD_BANK_INDICATORS
            ),
            fred_enabled=_env_bool("ENTITY_FRED_ENABLED", False),
            fred_api_key=os.getenv("ENTITY_FRED_API_KEY", "").strip(),
            fred_series=_env_csv(os.getenv("ENTITY_FRED_SERIES"), ()),
            gdelt_enabled=_env_bool("ENTITY_GDELT_ENABLED", False),
            gdelt_queries=tuple(
                value.strip()
                for value in os.getenv("ENTITY_GDELT_QUERIES", "").split("||")
                if value.strip()
            ),
            telegram_enabled=_env_bool("ENTITY_TELEGRAM_ENABLED", False),
            telegram_api_id=os.getenv("ENTITY_TELEGRAM_API_ID", "").strip(),
            telegram_api_hash=os.getenv("ENTITY_TELEGRAM_API_HASH", "").strip(),
            telegram_session_path=Path(os.getenv(
                "ENTITY_TELEGRAM_SESSION_PATH",
                "agent/private/telegram_entity"
            )),
            telegram_channels=tuple(
                value.strip().lstrip("@")
                for value in os.getenv("ENTITY_TELEGRAM_CHANNELS", "").split(",")
                if value.strip()
            ),
            telegram_poll_seconds=_env_int(
                "ENTITY_TELEGRAM_POLL_SECONDS", 120, minimum=60
            ),
            telegram_messages_per_channel=_env_int(
                "ENTITY_TELEGRAM_MESSAGES_PER_CHANNEL", 50, minimum=1
            ),
            telegram_deletion_scan_size=_env_int(
                "ENTITY_TELEGRAM_DELETION_SCAN_SIZE", 100, minimum=1
            ),
            telegram_media_enabled=_env_bool(
                "ENTITY_TELEGRAM_MEDIA_ENABLED", False
            ),
            telegram_media_directory=Path(os.getenv(
                "ENTITY_TELEGRAM_MEDIA_DIRECTORY",
                "agent/private/intelligence_media"
            )),
            telegram_media_max_bytes=_env_int(
                "ENTITY_TELEGRAM_MEDIA_MAX_BYTES", 10_000_000, minimum=1
            ),
            telegram_media_max_per_cycle=_env_int(
                "ENTITY_TELEGRAM_MEDIA_MAX_PER_CYCLE", 3, minimum=1
            ),
            telegram_media_whisper_model=(
                Path(value) if (
                    value := os.getenv("ENTITY_TELEGRAM_MEDIA_WHISPER_MODEL", "").strip()
                ) else None
            ),
            telegram_media_retention_hours=_env_int(
                "ENTITY_TELEGRAM_MEDIA_RETENTION_HOURS", 168, minimum=1
            ),
            gmail_enabled=_env_bool("ENTITY_GMAIL_ENABLED", False),
            gmail_credentials_path=Path(os.getenv(
                "ENTITY_GMAIL_CREDENTIALS_PATH",
                "agent/google_gmail_credentials.json"
            )),
            gmail_token_path=Path(os.getenv(
                "ENTITY_GMAIL_TOKEN_PATH",
                "agent/google_gmail_token.json"
            )),
            gmail_query=os.getenv(
                "ENTITY_GMAIL_QUERY",
                "newer_than:7d -in:spam -in:trash"
            ).strip(),
            outlook_enabled=_env_bool("ENTITY_OUTLOOK_ENABLED", False),
            outlook_client_id=os.getenv(
                "ENTITY_OUTLOOK_CLIENT_ID",
                ""
            ).strip(),
            outlook_tenant=os.getenv(
                "ENTITY_OUTLOOK_TENANT",
                "common"
            ).strip() or "common",
            outlook_token_cache_path=Path(os.getenv(
                "ENTITY_OUTLOOK_TOKEN_CACHE_PATH",
                "agent/outlook_mail_token_cache.json"
            )),
            outlook_folder=os.getenv(
                "ENTITY_OUTLOOK_FOLDER",
                "inbox"
            ).strip() or "inbox",
            mail_store_body=_env_bool("ENTITY_MAIL_STORE_BODY", False),
            x_enabled=_env_bool("ENTITY_X_ENABLED", False),
            x_bearer_token=os.getenv("ENTITY_X_BEARER_TOKEN", "").strip(),
            x_usernames=tuple(
                value.lstrip("@").strip()
                for value in os.getenv("ENTITY_X_USERNAMES", "").split(",")
                if value.strip()
            ),
            x_search_queries=tuple(
                value.strip()
                for value in os.getenv("ENTITY_X_SEARCH_QUERIES", "").split("||")
                if value.strip()
            ),
            x_poll_seconds=_env_int(
                "ENTITY_X_POLL_SECONDS",
                900,
                minimum=300
            ),
            x_max_results=_env_int(
                "ENTITY_X_MAX_RESULTS",
                25,
                minimum=10
            ),
            news_enabled=_env_bool("ENTITY_NEWS_ENABLED", True),
            news_rss_feeds=_env_news_feeds(
                os.getenv("ENTITY_NEWS_RSS_FEEDS")
            ),
            news_poll_seconds=_env_int(
                "ENTITY_NEWS_POLL_SECONDS", 300, minimum=60
            ),
            news_article_requests_per_cycle=_env_int(
                "ENTITY_NEWS_ARTICLE_REQUESTS_PER_CYCLE", 2,
                minimum=1, maximum=25
            ),
            polymarket_enabled=_env_bool(
                "ENTITY_POLYMARKET_ENABLED", True
            ),
            polymarket_poll_seconds=_env_int(
                "ENTITY_POLYMARKET_POLL_SECONDS", 300, minimum=60
            ),
            polymarket_max_markets=_env_int(
                "ENTITY_POLYMARKET_MAX_MARKETS", 50, minimum=1
            )
        )


def _env_bool(name, default=False):
    value = os.getenv(name)

    if value is None or not value.strip():
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default, minimum=0, maximum=None):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default

    value = max(minimum, value)
    return min(maximum, value) if maximum is not None else value


def _env_disk_limits():
    soft_default = 2_147_483_648
    hard_default = 3_221_225_472
    minimum_gap = 67_108_864
    try:
        soft = int(os.getenv(
            "ENTITY_INTELLIGENCE_DISK_SOFT_LIMIT_BYTES", str(soft_default)
        ))
        hard = int(os.getenv(
            "ENTITY_INTELLIGENCE_DISK_HARD_LIMIT_BYTES", str(hard_default)
        ))
    except ValueError:
        return soft_default, hard_default
    if soft < minimum_gap or hard - soft < minimum_gap:
        return soft_default, hard_default
    return soft, hard


def _env_float(name, default, minimum=0.0, maximum=None):
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    value = max(minimum, value)
    return min(maximum, value) if maximum is not None else value


def _env_news_feeds(value):
    if value is None:
        return DEFAULT_NEWS_RSS_FEEDS
    if not value.strip():
        return ()

    feeds = []
    for definition in value.split("||"):
        parts = [part.strip() for part in definition.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        try:
            credibility = float(parts[2]) if len(parts) > 2 else 0.8
        except ValueError:
            credibility = 0.8
        mode = parts[3].lower() if len(parts) > 3 else "feed-only"
        if mode not in {"feed-only", "publisher-page"}:
            mode = "feed-only"
        hosts = tuple(
            host.strip().lower() for host in (parts[4] if len(parts) > 4 else "").split(",")
            if host.strip()
        )
        feeds.append((parts[0], parts[1], max(0.0, min(1.0, credibility)),
                      mode, hosts))
    return tuple(feeds)


def _env_publisher_profiles(value):
    if value is None:
        return DEFAULT_PUBLISHER_PROFILES
    if not value.strip():
        return ()
    profiles = []
    for definition in value.split("||"):
        parts = [part.strip() for part in definition.split("|")]
        if len(parts) < 3 or not parts[0]:
            continue
        try:
            credibility = max(0.0, min(1.0, float(parts[1])))
            framing = max(0.0, min(1.0, float(parts[2])))
        except ValueError:
            continue
        profiles.append((
            parts[0].lower(), credibility, framing,
            parts[3] if len(parts) > 3 else "",
            parts[4] if len(parts) > 4 else "",
        ))
    return tuple(profiles)


def _env_csv(value, default):
    if value is None:
        return tuple(default)
    return tuple(item.strip() for item in value.split(",") if item.strip())
