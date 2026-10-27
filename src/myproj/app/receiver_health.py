import json
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock, Thread


class ReceiverHealth:
    def __init__(self) -> None:
        self._lock = Lock()
        self._ready = False
        self._heartbeat = time.monotonic()
        self._counts: Counter[str] = Counter()

    def touch(self, *, ready: bool | None = None, outcome: str | None = None) -> None:
        with self._lock:
            self._heartbeat = time.monotonic()
            if ready is not None:
                self._ready = ready
            if outcome:
                self._counts[outcome] += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            alive = time.monotonic() - self._heartbeat < 15
            return {
                "live": alive,
                "ready": alive and self._ready,
                "counts": dict(self._counts),
            }


class HealthServer:
    def __init__(self, host: str, port: int, state: ReceiverHealth) -> None:
        class Handler(BaseHTTPRequestHandler):
            def setup(self) -> None:
                self.request.settimeout(2)
                super().setup()

            def do_GET(self) -> None:
                data = state.snapshot()
                if self.path not in {"/health/live", "/health/ready"}:
                    self.send_error(404)
                    return
                body = json.dumps(data).encode()
                key = "live" if self.path.endswith("/live") else "ready"
                self.send_response(200 if data[key] else 503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = HTTPServer((host, port), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
