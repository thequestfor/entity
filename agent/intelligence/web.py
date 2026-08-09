import json
import threading
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_ROOT = PROJECT_ROOT / "intelligence_dashboard"


class _DashboardHandler(SimpleHTTPRequestHandler):
    server_version = "EntityIntelligence/0.1"

    def do_GET(self):
        parsed = urlsplit(self.path)

        if parsed.path == "/api/intelligence/overview":
            self._send_json(self.server.intelligence_store.overview())
            return

        if parsed.path == "/api/intelligence/documents":
            query = parse_qs(parsed.query)
            limit = _query_int(query, "limit", 50)
            category = (query.get("category") or [None])[0]
            self._send_json(
                {
                    "documents": self.server.intelligence_store.list_documents(
                        limit=limit,
                        category=category
                    )
                }
            )
            return

        if parsed.path == "/api/intelligence/sources":
            self._send_json(
                {"sources": self.server.intelligence_store.list_sources()}
            )
            return

        if parsed.path == "/api/intelligence/source-policies":
            self._send_json({
                "policies":self.server.intelligence_store.list_source_policies()
            })
            return

        if parsed.path == "/api/intelligence/reputations":
            query = parse_qs(parsed.query)
            self._send_json({
                "reputations": (
                    self.server.intelligence_store.list_publisher_reputations(
                        limit=_query_int(query, "limit", 200)
                    )
                )
            })
            return

        if parsed.path == "/api/intelligence/reputation-outcomes":
            query = parse_qs(parsed.query)
            self._send_json({
                "outcomes": self.server.intelligence_store.list_publisher_outcomes(
                    publisher_key=(query.get("publisher") or [None])[0],
                    limit=_query_int(query, "limit", 100)
                )
            })
            return

        if parsed.path == "/api/intelligence/reliability-cells":
            query = parse_qs(parsed.query)
            self._send_json({"cells": self.server.intelligence_store.list_reliability_cells(
                publisher_key=(query.get("publisher") or [None])[0],
                limit=_query_int(query, "limit", 200)
            )})
            return

        if parsed.path == "/api/intelligence/verification-tasks":
            query = parse_qs(parsed.query)
            self._send_json({"tasks": self.server.intelligence_store.list_verification_tasks(
                status=(query.get("status") or ["pending"])[0],
                limit=_query_int(query, "limit", 100)
            )})
            return

        if parsed.path == "/api/intelligence/gaps":
            query=parse_qs(parsed.query)
            self._send_json({"gaps": self.server.intelligence_store.list_intelligence_gaps(
                status=(query.get("status") or ["open"])[0],
                limit=_query_int(query,"limit",100)
            )})
            return

        if parsed.path == "/api/intelligence/evaluations":
            query=parse_qs(parsed.query)
            self._send_json(self.server.intelligence_store.intelligence_evaluations(
                limit=_query_int(query,"limit",20)
            ))
            return

        if parsed.path == "/api/intelligence/epistemic-health":
            self._send_json(self.server.intelligence_store.epistemic_health())
            return

        if parsed.path == "/api/intelligence/open-source-enrichment":
            self._send_json(
                self.server.intelligence_store.open_source_enrichment_overview()
            )
            return

        if parsed.path == "/api/intelligence/reasoning-budget":
            self._send_json(
                self.server.intelligence_store.reasoning_budget_overview()
            )
            return

        if parsed.path == "/api/intelligence/early-reports":
            query = parse_qs(parsed.query)
            self._send_json({
                "reports": self.server.intelligence_store.list_early_reports(
                    limit=_query_int(query, "limit", 50)
                )
            })
            return

        if parsed.path == "/api/intelligence/reasoning":
            query=parse_qs(parsed.query)
            self._send_json(self.server.intelligence_store.reasoning_overview(
                limit=_query_int(query,"limit",50)
            ))
            return

        if parsed.path == "/api/intelligence/forecasts":
            query = parse_qs(parsed.query)
            self._send_json({
                "forecasts": self.server.intelligence_store.list_forecasts(
                    limit=_query_int(query, "limit", 50),
                    status=(query.get("status") or [None])[0]
                ),
                "calibration": self.server.intelligence_store.forecast_calibration()
            })
            return

        if parsed.path == "/api/intelligence/clustering":
            query = parse_qs(parsed.query)
            self._send_json({
                "overview": self.server.intelligence_store.clustering_overview(),
                "merge_candidates": (
                    self.server.intelligence_store.list_merge_candidates(
                        limit=_query_int(query, "limit", 50)
                    )
                )
            })
            return

        if parsed.path == "/api/intelligence/situations":
            query = parse_qs(parsed.query)
            self._send_json(
                {
                    "situations": self.server.intelligence_store.list_situations(
                        limit=_query_int(query, "limit", 50),
                        category=(query.get("category") or [None])[0],
                        status=(query.get("status") or [None])[0],
                        located_only=_query_bool(query, "located")
                    )
                }
            )
            return

        if parsed.path == "/api/intelligence/geography":
            query = parse_qs(parsed.query)
            self._send_json(self.server.intelligence_store.geography_overview(
                limit=_query_int(query, "limit", 200)
            ))
            return

        if parsed.path == "/api/intelligence/world-graph":
            self._send_json(self.server.intelligence_store.world_graph_overview())
            return

        if parsed.path == "/api/intelligence/event-fusion":
            self._send_json(self.server.intelligence_store.fusion_overview())
            return

        if parsed.path == "/api/intelligence/event-fusion/reviews":
            query = parse_qs(parsed.query)
            self._send_json({
                "reviews": self.server.intelligence_store.list_fusion_reviews(
                    limit=_query_int(query, "limit", 100),
                    status=(query.get("status") or ["pending"])[0]
                )
            })
            return

        if parsed.path == "/api/intelligence/world-events":
            query = parse_qs(parsed.query)
            bbox = _query_bbox(query) if "bbox" in query else None
            self._send_json({"events":self.server.intelligence_store.list_world_events(
                limit=_query_int(query,"limit",100),
                status=(query.get("status") or [None])[0],
                event_type=(query.get("type") or [None])[0],
                country=(query.get("country") or [None])[0],bbox=bbox
            )})
            return

        world_event_prefix = "/api/intelligence/world-events/"
        if parsed.path.startswith(world_event_prefix):
            event_id = unquote(parsed.path[len(world_event_prefix):])
            detail = self.server.intelligence_store.get_world_event(event_id)
            if detail is None:
                self._send_json({"error":"World event not found."}, status=HTTPStatus.NOT_FOUND)
            else:
                self._send_json(detail)
            return

        if parsed.path == "/api/intelligence/aircraft":
            query = parse_qs(parsed.query)
            self._send_json({"aircraft": self.server.intelligence_store.list_aircraft_states(
                limit=_query_int(query, "limit", 300)
            )})
            return

        if parsed.path == "/api/intelligence/map/features":
            query = parse_qs(parsed.query)
            bbox = _query_bbox(query)
            layers = _query_csv(query, "layers")
            since_at = (query.get("since") or [None])[0]
            minimum_severity = _query_float(query, "severity", 0.0)
            zoom = _query_int(query, "zoom", 2)
            self._send_json({
                "features": self.server.intelligence_store.list_geo_features(
                    bbox=bbox, layers=layers, since_at=since_at,
                    minimum_severity=minimum_severity,
                    limit=_query_int(query, "limit", 1000)
                ),
                "cells": self.server.intelligence_store.list_geo_cells(
                    bbox=bbox, layers=layers, since_at=since_at,
                    limit=_query_int(query, "cell_limit", 1000)
                ) if zoom <= 6 else [],
                "anomalies": self.server.intelligence_store.list_geo_anomalies(
                    bbox=bbox, limit=100
                )
            })
            return

        if parsed.path == "/api/intelligence/map/weather":
            query = parse_qs(parsed.query)
            self._send_json({
                "forecasts": self.server.intelligence_store.list_weather_forecasts(
                    bbox=_query_bbox(query),
                    valid_at=(query.get("valid_at") or [None])[0],
                    limit=_query_int(query, "limit", 500)
                )
            })
            return

        if parsed.path == "/api/intelligence/map/infrastructure":
            query = parse_qs(parsed.query)
            self._send_json({
                "assets": self.server.intelligence_store.list_infrastructure_assets(
                    bbox=_query_bbox(query),
                    asset_types=_query_csv(query, "types"),
                    limit=_query_int(query, "limit", 1000)
                )
            })
            return

        if parsed.path == "/api/intelligence/map/regional-assessment":
            query = parse_qs(parsed.query)
            self._send_json(self.server.intelligence_store.regional_assessment(
                bbox=_query_bbox(query), layers=_query_csv(query, "layers"),
                since_at=(query.get("since") or [None])[0]
            ))
            return

        if parsed.path == "/api/intelligence/country-profile":
            query = parse_qs(parsed.query)
            profile = self.server.intelligence_store.get_country_profile(
                (query.get("country") or [""])[0]
            )
            if profile is None:
                self._send_json({"error":"Country profile not found."}, status=HTTPStatus.NOT_FOUND)
            else:
                self._send_json(profile)
            return

        if parsed.path == "/api/intelligence/map-commentary":
            query = parse_qs(parsed.query)
            self._send_json(self.server.intelligence_store.map_commentary(
                kind=(query.get("type") or [""])[0],
                identifier=(query.get("id") or [""])[0],
                country=(query.get("country") or [""])[0]
            ))
            return

        situation_prefix = "/api/intelligence/situations/"
        if parsed.path.startswith(situation_prefix):
            situation_id = unquote(parsed.path[len(situation_prefix):])
            detail = self.server.intelligence_store.get_situation(situation_id)
            if detail is None:
                self._send_json(
                    {"error": "Situation not found."},
                    status=HTTPStatus.NOT_FOUND
                )
            else:
                self._send_json(detail)
            return

        if parsed.path == "/api/intelligence/briefing":
            self._send_json(
                self.server.intelligence_store.latest_briefing()
            )
            return

        if parsed.path == "/api/intelligence/outbox":
            query = parse_qs(parsed.query)
            after = _query_int(query, "after", 0)
            self._send_json(
                {
                    "events": self.server.intelligence_store.outbox_since(
                        after_id=after
                    )
                }
            )
            return

        if parsed.path == "/":
            self.path = "/index.html"
        elif parsed.path.startswith("/api/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        super().do_GET()

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self' https://raw.githubusercontent.com; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com; script-src 'self' https://unpkg.com; "
            "img-src 'self' data: https://*.basemaps.cartocdn.com https://unpkg.com"
        )
        super().end_headers()

    def log_message(self, format, *args):
        return

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(
            payload,
            separators=(",", ":"),
            default=str
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class IntelligenceDashboard:
    def __init__(
        self,
        store,
        host="127.0.0.1",
        port=8770,
        static_root=DASHBOARD_ROOT,
        open_browser=False
    ):
        self.store = store
        self.host = host
        self.port = int(port)
        self.static_root = Path(static_root)
        self.open_browser = bool(open_browser)
        self._server = None
        self._thread = None

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    @property
    def url(self):
        port = self._server.server_port if self._server else self.port
        return f"http://{self.host}:{port}/"

    def start(self):
        if self.running:
            return

        if not (self.static_root / "index.html").is_file():
            raise RuntimeError(
                f"Intelligence dashboard is missing: {self.static_root}"
            )

        handler = partial(
            _DashboardHandler,
            directory=str(self.static_root)
        )
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._server.intelligence_store = self.store
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="entity-intelligence-dashboard",
            daemon=True
        )
        self._thread.start()
        print(f"Entity intelligence dashboard: {self.url}")
        if self.open_browser:
            webbrowser.open(self.url, new=1)

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None


def _query_int(query, name, default):
    try:
        return int((query.get(name) or [default])[0])
    except (TypeError, ValueError):
        return default


def _query_bool(query, name, default=False):
    value = str((query.get(name) or [default])[0]).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _query_float(query, name, default=0.0):
    try:
        return float((query.get(name) or [default])[0])
    except (TypeError, ValueError):
        return default


def _query_csv(query, name):
    return tuple(
        item.strip().lower()
        for item in str((query.get(name) or [""])[0]).split(",")
        if item.strip()
    )


def _query_bbox(query):
    value = str((query.get("bbox") or ["-180,-90,180,90"])[0])
    try:
        west, south, east, north = (float(item.strip()) for item in value.split(","))
    except (TypeError, ValueError):
        return (-180.0, -90.0, 180.0, 90.0)
    west = max(-180.0, min(180.0, west))
    east = max(-180.0, min(180.0, east))
    south = max(-90.0, min(90.0, south))
    north = max(-90.0, min(90.0, north))
    if south > north:
        south, north = north, south
    return west, south, east, north
