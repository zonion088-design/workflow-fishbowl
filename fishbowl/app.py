"""Application wiring: scanner thread + HTTP server."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter, MultiAdapter
from .config import Config
from .scanner import Scanner
from .server import make_server
from .store import Store


class App:
    """Owns the store, the scanner and (when running) the web server."""

    def __init__(self, cfg: Config, demo: bool = False):
        if demo:
            from .demo import prepare_demo, Replay
            cfg = prepare_demo(cfg)
            self._replay = Replay(cfg)
        else:
            self._replay = None
        self.cfg = cfg
        self.store = Store(cfg)
        if demo or not cfg.include_codex:
            self.adapter = ClaudeCodeAdapter(cfg.source_root)
        else:
            self.adapter = MultiAdapter([
                ClaudeCodeAdapter(cfg.source_root),
                CodexAdapter(Path.home() / ".codex" / "sessions"),
                CodexAdapter(Path.home() / ".codex" / "archived_sessions"),
            ])
        self.scanner = Scanner(self.adapter, self.store, cfg)
        self._scan_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._server = None

    # ------------------------------------------------------------------

    def scan_once(self):
        return self.scanner.scan_once()

    def snapshot(self):
        """Sessions with statuses (used by --dump and tests)."""
        from .status import classify
        now = time.time()
        out = []
        for s in list(self.store.sessions.values()):
            s.status = classify(s, self.cfg, now)
            out.append(s.to_dict())
        out.sort(key=lambda d: d.get("last_activity_at") or "",
                 reverse=True)
        return out

    # ------------------------------------------------------------------

    def run(self, open_browser: bool = False) -> None:
        if self.cfg.cache_path:
            self.scanner.load_state(self.cfg.cache_path)

        if self._replay is not None:
            self._replay.start()

        self._server = make_server(self)

        self._stop.clear()
        self._scan_thread = threading.Thread(
            target=self._scan_loop, name="fishbowl-scan", daemon=True)
        self._scan_thread.start()

        if open_browser:
            import webbrowser
            threading.Timer(0.8, lambda: webbrowser.open(
                f"http://127.0.0.1:{self.cfg.port}")).start()

        print(f"fishbowl: watching {self.cfg.source_root}")
        print(f"fishbowl: http://127.0.0.1:{self.cfg.port} "
              f"(Ctrl+C to stop)")
        try:
            self._server.serve_forever(poll_interval=0.5)
        finally:
            self.shutdown()

    def _scan_loop(self) -> None:
        saves = 0
        while not self._stop.is_set():
            try:
                self.scanner.scan_once()
            except Exception as exc:            # keep the loop alive
                print(f"fishbowl: scan error: {exc!r}", flush=True)
            saves += 1
            if self.cfg.cache_path and saves % 5 == 0:
                try:
                    self.scanner.save_state(self.cfg.cache_path)
                except OSError:
                    pass
            self._stop.wait(self.cfg.poll_interval)

    def shutdown(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        if self._server is not None:
            threading.Thread(target=self._server.shutdown,
                             daemon=True).start()
            self._server = None
        if self._replay is not None:
            self._replay.stop()
            self._replay = None
        if self.cfg.cache_path:
            try:
                self.scanner.save_state(self.cfg.cache_path)
            except OSError:
                pass


def build_app(cfg: Config, demo: bool = False) -> App:
    return App(cfg, demo=demo)
