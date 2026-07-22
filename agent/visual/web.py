import json
import os
import queue
import subprocess
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _VisualRequestHandler(SimpleHTTPRequestHandler):
    server_version = "EntityVisual/1.0"

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/events":
            self._serve_events()
            return

        super().do_GET()

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format, *args):
        return

    def _serve_events(self):
        events = self.server.visual_events
        subscriber = events.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "keep-alive")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        try:
            initial = events.latest

            if initial:
                self._write_event(initial)

            while not events.closed:
                try:
                    event = subscriber.get(timeout=10)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue

                self._write_event(event)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            events.unsubscribe(subscriber)

    def _write_event(self, event):
        payload = json.dumps(event, separators=(",", ":"))
        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()


class _VisualEvents:
    def __init__(self):
        self._lock = threading.RLock()
        self._subscribers = []
        self.latest = None
        self.closed = False

    def publish(self, event):
        payload = dict(event)

        with self._lock:
            self.latest = payload
            subscribers = list(self._subscribers)

        for subscriber in subscribers:
            try:
                subscriber.put_nowait(payload)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass

                try:
                    subscriber.put_nowait(payload)
                except queue.Full:
                    pass

    def subscribe(self):
        subscriber = queue.Queue(maxsize=4)

        with self._lock:
            self._subscribers.append(subscriber)

        return subscriber

    def unsubscribe(self, subscriber):
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def close(self):
        self.closed = True

    def reopen(self):
        self.closed = False


class WebVisualSink:
    enabled = True

    def __init__(
        self,
        mode,
        host=None,
        port=None,
        open_browser=None,
        project_root=None
    ):
        if mode not in {"2d", "3d"}:
            raise ValueError(f"Unsupported web visual mode: {mode}")

        self.mode = mode
        self.host = host or os.getenv(
            "ENTITY_VISUAL_HOST",
            "127.0.0.1"
        )
        self.port = int(
            port
            if port is not None
            else os.getenv("ENTITY_VISUAL_PORT", "8765")
        )
        self.open_browser = (
            self._env_bool("ENTITY_VISUAL_OPEN_BROWSER", True)
            if open_browser is None
            else bool(open_browser)
        )
        self.project_root = Path(project_root or PROJECT_ROOT)
        self.events = _VisualEvents()
        self._server = None
        self._thread = None

    @property
    def url(self):
        port = self._server.server_port if self._server else self.port
        return f"http://{self.host}:{port}/"

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        self.events.reopen()
        root = self._static_root()
        handler = partial(_VisualRequestHandler, directory=str(root))

        try:
            self._server = ThreadingHTTPServer(
                (self.host, self.port),
                handler
            )
        except OSError as exc:
            raise RuntimeError(
                f"Could not start the {self.mode} visual interface on "
                f"{self.host}:{self.port}: {exc}"
            ) from exc

        self._server.visual_events = self.events
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"entity-{self.mode}-visual",
            daemon=True
        )
        self._thread.start()
        print(f"Entity {self.mode} visual interface: {self.url}")

        if self.open_browser:
            webbrowser.open(self.url, new=1)

    def publish(self, event):
        self.events.publish(event)

    def close(self):
        self.events.close()

        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _static_root(self):
        if self.mode == "2d":
            root = self.project_root / "visual_mockup"
        else:
            source = self.project_root / "visual_interface"
            self._build_three_interface(source)
            root = source / "dist"

        if not (root / "index.html").is_file():
            raise RuntimeError(
                f"Visual interface entry point is missing: {root / 'index.html'}"
            )

        return root

    def _build_three_interface(self, source):
        if not (source / "package.json").is_file():
            raise RuntimeError("The 3D visual interface source is missing.")

        try:
            if not (source / "node_modules" / ".bin" / "vite").exists():
                subprocess.run(
                    ["npm", "ci"],
                    cwd=source,
                    check=True
                )
            subprocess.run(
                ["npm", "run", "build"],
                cwd=source,
                check=True
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "The 3D visual interface requires Node.js and npm."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                "The 3D visual interface failed to build."
            ) from exc

    def _env_bool(self, name, default=False):
        value = os.getenv(name)

        if value is None or value.strip() == "":
            return default

        return value.strip().lower() in {"1", "true", "yes", "on"}
