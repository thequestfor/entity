import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_NEWS_RSS_FEEDS = (
    ("BBC News - World", "https://feeds.bbci.co.uk/news/world/rss.xml", 0.85),
    ("NPR - World", "https://feeds.npr.org/1004/rss.xml", 0.85),
)


@dataclass(frozen=True)
class IntelligenceConfig:
    enabled: bool = False
    database_path: Path = Path("agent/world_intelligence.db")
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8770
    dashboard_enabled: bool = True
    worker_poll_seconds: int = 30
    request_timeout_seconds: int = 15
    max_items_per_source: int = 50
    reputation_enabled: bool = True
    reputation_maturity_hours: float = 6.0
    reputation_max_adjustment: float = 0.15
    forecast_max_active: int = 12
    forecast_per_cycle: int = 2
    reliefweb_appname: str = ""
    reliefweb_enabled: bool = True
    usgs_enabled: bool = True
    eonet_enabled: bool = True
    gdacs_enabled: bool = True
    who_outbreaks_enabled: bool = True
    nws_alerts_enabled: bool = True
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
    news_rss_feeds: tuple[tuple[str, str, float], ...] = DEFAULT_NEWS_RSS_FEEDS
    news_poll_seconds: int = 300
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
            worker_poll_seconds=_env_int(
                "ENTITY_INTELLIGENCE_WORKER_POLL_SECONDS",
                30,
                minimum=5
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
            forecast_max_active=_env_int(
                "ENTITY_FORECAST_MAX_ACTIVE", 12, minimum=1
            ),
            forecast_per_cycle=_env_int(
                "ENTITY_FORECAST_PER_CYCLE", 2, minimum=1
            ),
            reliefweb_appname=os.getenv(
                "ENTITY_RELIEFWEB_APPNAME",
                ""
            ).strip(),
            reliefweb_enabled=_env_bool(
                "ENTITY_RELIEFWEB_ENABLED",
                True
            ),
            usgs_enabled=_env_bool("ENTITY_USGS_ENABLED", True),
            eonet_enabled=_env_bool("ENTITY_EONET_ENABLED", True),
            gdacs_enabled=_env_bool("ENTITY_GDACS_ENABLED", True),
            who_outbreaks_enabled=_env_bool(
                "ENTITY_WHO_OUTBREAKS_ENABLED", True
            ),
            nws_alerts_enabled=_env_bool("ENTITY_NWS_ALERTS_ENABLED", True),
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


def _env_int(name, default, minimum=0):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default

    return max(minimum, value)


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
        feeds.append((
            parts[0], parts[1], max(0.0, min(1.0, credibility))
        ))
    return tuple(feeds)
