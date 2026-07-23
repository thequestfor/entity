import json
import threading
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

        if parsed.path == "/api/intelligence/situations":
            query = parse_qs(parsed.query)
            self._send_json(
                {
                    "situations": self.server.intelligence_store.list_situations(
                        limit=_query_int(query, "limit", 50),
                        category=(query.get("category") or [None])[0],
                        status=(query.get("status") or [None])[0]
                    )
                }
            )
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
            "default-src 'self'; connect-src 'self'; style-src 'self'; "
            "script-src 'self'; img-src 'self' data:"
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
        static_root=DASHBOARD_ROOT
    ):
        self.store = store
        self.host = host
        self.port = int(port)
        self.static_root = Path(static_root)
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
