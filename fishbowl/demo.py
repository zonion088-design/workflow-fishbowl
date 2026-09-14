"""Demo replay - makes the dashboard come alive on synthetic data.

``--demo`` points the scanner at the bundled fixtures via a *temporary
copy* (the repo itself is never modified), then appends lines of a
scripted session every few seconds so visitors can watch an "agent"
work in real time without having Claude Code installed.
"""
from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config

REPLAY_INTERVAL = 3.0          # seconds between appended lines
DEMO_PROJECT_DIR = "C--Users-demo-fishbowl-demo"


def prepare_demo(cfg: Config) -> Config:
    """Generate a fresh fixture tree in a temp dir (timestamps relative
    to *now*, so statuses look right whenever the demo runs) and return
    an updated Config pointing there (cache disabled)."""
    from .fixtures_gen import make_fixture_tree
    dest = Path(tempfile.mkdtemp(prefix="fishbowl-demo-")) / "projects"
    make_fixture_tree(dest, now=datetime.now(timezone.utc))
    return dataclasses.replace(cfg, source_root=dest, cache_path=None)


class Replay:
    """Drip-feeds a scripted session into the demo tree."""

    def __init__(self, cfg: Config, interval: float = REPLAY_INTERVAL):
        self.cfg = cfg
        self.interval = interval
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="fishbowl-demo", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        now = datetime.now(timezone.utc)
        sid = str(uuid.uuid4())
        path = self.cfg.source_root / DEMO_PROJECT_DIR / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        for line in _script(sid, now):
            if self._stop.is_set():
                break
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
            self._stop.wait(self.interval)


def _script(sid: str, t0: datetime) -> list[dict]:
    """A short deterministic 'agent at work' script."""
    def ts(sec: float) -> str:
        return (t0 + timedelta(seconds=sec)).astimezone(timezone.utc)\
            .strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def user(sec, text):
        return {"type": "user", "timestamp": ts(sec), "isSidechain": False,
                "cwd": r"C:\Users\demo\fishbowl-demo", "sessionId": sid,
                "version": "2.1.0", "gitBranch": "main",
                "message": {"role": "user", "content": text}}

    def assistant(sec, content):
        return {"type": "assistant", "timestamp": ts(sec),
                "isSidechain": False,
                "cwd": r"C:\Users\demo\fishbowl-demo", "sessionId": sid,
                "version": "2.1.0", "gitBranch": "main",
                "message": {"id": "msg_demo", "role": "assistant",
                            "model": "claude-sonnet-5",
                            "content": content,
                            "usage": {"input_tokens": 120,
                                      "cache_read_input_tokens": 1500,
                                      "cache_creation_input_tokens": 0,
                                      "output_tokens": 80,
                                      "output_tokens_details": {
                                          "thinking_tokens": 0}}}}

    def result(sec, call_id, stdout):
        return {"type": "user", "timestamp": ts(sec), "isSidechain": False,
                "cwd": r"C:\Users\demo\fishbowl-demo", "sessionId": sid,
                "version": "2.1.0", "gitBranch": "main",
                "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": call_id,
                     "content": stdout}]},
                "toolUseResult": {"stdout": stdout, "stderr": ""}}

    def call(sec, call_id, name, tool_input):
        return assistant(sec, [
            {"type": "tool_use", "id": call_id, "name": name,
             "input": tool_input}])

    return [
        user(0, "Find slow tests in the demo repo"),
        {"type": "ai-title", "aiTitle": "Demo: find slow tests",
         "sessionId": sid, "timestamp": ts(0)},
        call(1, "demo_1", "Glob", {"pattern": "tests/**/*.py"}),
        result(3, "demo_1", "tests/test_pay.py\ntests/test_api.py"),
        call(5, "demo_2", "Bash",
             {"command": "python -m pytest tests/ --durations=10"}),
        result(25, "demo_2", "42 passed, 3 slowest: test_charge 8.1s"),
        call(27, "demo_3", "Read", {"file_path": "tests/test_pay.py"}),
        result(29, "demo_3", "140 lines"),
    ]
