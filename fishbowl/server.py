"""Local HTTP server - loopback only, GET only, zero dependencies."""
from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__

HOST = "127.0.0.1"            # localhost only - by design, not config
WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_BODY = 0                  # reads are tiny; no uploads, ever

_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def make_server(app):
    handler = _make_handler(app)

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    return Server((HOST, app.cfg.port), handler)


def _make_handler(app):
    from .api import handle_api

    class Handler(BaseHTTPRequestHandler):
        server_version = f"fishbowl/{__version__}"

        # -- logging: quiet by default -------------------------------
        def log_message(self, fmt, *args):        # noqa: N802
            pass

        # -- routing -------------------------------------------------
        def do_GET(self):                          # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/api/"):
                query = parse_qs(parsed.query)
                status, payload = handle_api(app, path, query)
                self._send_json(status, payload)
                return
            self._send_static(path)

        # -- unsupported verbs are refused hard (read-only service) --
        def do_POST(self):                         # noqa: N802
            self._send_json(405, {"error": "read-only service"})

        do_PUT = do_DELETE = do_PATCH = do_POST

        # -- helpers -------------------------------------------------
        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, path: str) -> None:
            if path in ("/", "/index.html"):
                file = WEB_DIR / "index.html"
            else:
                # only flat files from web/; no traversal
                candidate = (WEB_DIR / path.lstrip("/")).resolve()
                if not str(candidate).startswith(str(WEB_DIR)) \
                        or candidate.is_dir():
                    self._send_json(404, {"error": "not found"})
                    return
                file = candidate
            try:
                body = file.read_bytes()
            except OSError:
                self._send_json(404, {"error": "not found"})
                return
            mime = _STATIC_TYPES.get(file.suffix.lower()) \
                or mimetypes.guess_type(file.name)[0] or "text/plain"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler
