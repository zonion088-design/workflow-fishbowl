"""Synthetic transcript fixtures for tests and demo mode.

Everything fishbowl shows must be reproducible without a real
``~/.claude`` directory - and the repo must never contain real
transcripts (they hold source code and secrets from real machines).
This generator emits deterministic, seeded, fake-but-shaped-right
session trees.

Timestamps are computed relative to ``now`` (injectable) and file
mtimes are backdated to match, so stall/idle logic can be tested
without sleeping.
"""
from __future__ import annotations

import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEMO_CWD = r"C:\Users\demo\fishbowl-demo"
DEMO_PROJECT_DIR = "C--Users-demo-fishbowl-demo"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class LineFactory:
    """Builds transcript lines with a consistent session identity."""

    def __init__(self, session_id: str, cwd: str = DEMO_CWD,
                 branch: str = "main", version: str = "2.1.0"):
        self.sid = session_id
        self.cwd = cwd
        self.branch = branch
        self.version = version
        self.parent = None

    def _base(self, ts: datetime, t: str) -> dict:
        obj = {
            "parentUuid": self.parent, "isSidechain": False,
            "userType": "external", "cwd": self.cwd, "sessionId": self.sid,
            "version": self.version, "gitBranch": self.branch,
            "type": t, "timestamp": _iso(ts),
            "uuid": str(uuid.uuid4()),
        }
        return obj

    def user_prompt(self, ts, text: str) -> dict:
        o = self._base(ts, "user")
        o["message"] = {"role": "user", "content": text}
        return o

    def assistant(self, ts, content: list, usage: dict | None = None,
                  model: str = "claude-sonnet-5") -> dict:
        o = self._base(ts, "assistant")
        o["message"] = {
            "id": f"msg_{uuid.uuid4().hex[:24]}", "role": "assistant",
            "model": model,
            "content": content,
            "usage": usage or {"input_tokens": 100,
                               "cache_read_input_tokens": 1000,
                               "cache_creation_input_tokens": 0,
                               "output_tokens": 50,
                               "output_tokens_details": {"thinking_tokens": 0}},
        }
        return o

    def thinking(self, ts, text: str) -> dict:
        return self.assistant(ts, [{"type": "thinking", "thinking": text}])

    def text(self, ts, text: str) -> dict:
        return self.assistant(ts, [{"type": "text", "text": text}])

    def tool_call(self, ts, call_id: str, name: str,
                  tool_input: dict) -> dict:
        return self.assistant(ts, [
            {"type": "tool_use", "id": call_id, "name": name,
             "input": tool_input}])

    def tool_result(self, ts, call_id: str, stdout: str = "",
                    stderr: str = "", error: bool = False) -> dict:
        o = self._base(ts, "user")
        o["message"] = {"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": call_id,
            "content": stdout or stderr or "ok",
            "is_error": error}]}
        o["toolUseResult"] = ({"stdout": stdout, "stderr": stderr}
                              if not error else {"error": stderr})
        return o

    def ai_title(self, ts, title: str) -> dict:
        o = self._base(ts, "ai-title")
        o["aiTitle"] = title
        return o

    def attachment(self, ts) -> dict:
        o = self._base(ts, "attachment")
        o["attachment"] = {"type": "queued"}
        return o


def _write_jsonl(path: Path, lines: list[dict],
                 mtime: datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for obj in lines:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    if mtime is not None:
        _backdate(path, mtime)


def _write_json(path: Path, obj: dict, mtime: datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")
    if mtime is not None:
        _backdate(path, mtime)


def _backdate(path: Path, dt: datetime) -> None:
    ts = dt.timestamp()
    os.utime(path, (ts, ts))


def _rand_sid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


# ---------------------------------------------------------------------------
# scenario builders - each returns the session id

def completed(dest: Path, now: datetime, rng: random.Random) -> str:
    """A normal session that finished two hours ago."""
    sid = _rand_sid(rng)
    f = LineFactory(sid)
    lines = [
        f.user_prompt(now - timedelta(hours=3),
                      "Add a rate limiter to the API client"),
        f.ai_title(now - timedelta(hours=3), "Rate limiter for API client"),
        f.thinking(now - timedelta(hours=3, minutes=1),
                   "I will look at the client module first."),
        f.tool_call(now - timedelta(hours=2, minutes=58), "call_a1",
                    "Glob", {"pattern": "src/**/*.py"}),
        f.tool_result(now - timedelta(hours=2, minutes=58, seconds=2),
                      "call_a1", stdout="src/client.py\nsrc/api.py"),
        f.tool_call(now - timedelta(hours=2, minutes=50), "call_a2",
                    "Read", {"file_path": "src/client.py"}),
        f.tool_result(now - timedelta(hours=2, minutes=49, seconds=40),
                      "call_a2", stdout="180 lines"),
        f.text(now - timedelta(hours=2, minutes=40),
               "Done. Added a token bucket limiter to src/client.py."),
    ]
    _write_jsonl(dest / DEMO_PROJECT_DIR / f"{sid}.jsonl", lines,
                 mtime=now - timedelta(hours=2, minutes=40))
    return sid


def active(dest: Path, now: datetime, rng: random.Random) -> str:
    """A live session: last event is a tool call 30 seconds ago."""
    sid = _rand_sid(rng)
    f = LineFactory(sid, branch="feature/limiter")
    lines = [
        f.user_prompt(now - timedelta(minutes=10),
                      "Refactor the payment module"),
        f.ai_title(now - timedelta(minutes=10), "Payment refactor"),
        f.tool_call(now - timedelta(minutes=9), "call_b1", "Grep",
                    {"pattern": "def charge", "path": "src/pay"}),
        f.tool_result(now - timedelta(minutes=8, seconds=55), "call_b1",
                      stdout="src/pay/charge.py:12"),
        f.tool_call(now - timedelta(seconds=30), "call_b2", "Bash",
                    {"command": "python -m pytest tests/test_pay.py -x"}),
    ]
    _write_jsonl(dest / DEMO_PROJECT_DIR / f"{sid}.jsonl", lines,
                 mtime=now - timedelta(seconds=30))
    return sid


def stalled(dest: Path, now: datetime, rng: random.Random) -> str:
    """A stuck session: a tool call 10 minutes ago, no result, silent."""
    sid = _rand_sid(rng)
    f = LineFactory(sid, branch="bugfix/hang")
    lines = [
        f.user_prompt(now - timedelta(minutes=40),
                      "Why does the import job hang?"),
        f.ai_title(now - timedelta(minutes=40), "Import job hangs"),
        f.tool_call(now - timedelta(minutes=10), "call_c1", "Bash",
                    {"command": "curl -m 600 http://internal-svc/api"}),
    ]
    _write_jsonl(dest / DEMO_PROJECT_DIR / f"{sid}.jsonl", lines,
                 mtime=now - timedelta(minutes=10))
    return sid


def with_subagents(dest: Path, now: datetime, rng: random.Random) -> str:
    """A session with two subagents and one workflow."""
    sid = _rand_sid(rng)
    f = LineFactory(sid)
    sub_dir = dest / DEMO_PROJECT_DIR / sid / "subagents"

    _write_jsonl(dest / DEMO_PROJECT_DIR / f"{sid}.jsonl", [
        f.user_prompt(now - timedelta(minutes=25),
                      "Audit the repo for dead code"),
        f.ai_title(now - timedelta(minutes=25), "Dead code audit"),
        f.tool_call(now - timedelta(minutes=24), "call_d0", "Agent",
                    {"description": "fan out the audit", "prompt": "go"}),
        f.tool_result(now - timedelta(minutes=6), "call_d0",
                      stdout="2 subagents completed"),
        f.text(now - timedelta(minutes=5),
               "Audit finished: 3 dead modules found."),
    ], mtime=now - timedelta(minutes=5))

    for i, (agent_type, desc) in enumerate([
            ("Explore", "search for unused exports"),
            ("general-purpose", "verify findings against tests")]):
        stem = f"agent-{rng.getrandbits(64):016x}"
        af = LineFactory(sid)
        _write_jsonl(sub_dir / f"{stem}.jsonl", [
            af.thinking(now - timedelta(minutes=23, seconds=i),
                        f"Auditing ({desc})"),
            af.tool_call(now - timedelta(minutes=22, seconds=i),
                         f"call_s{i}", "Grep", {"pattern": "export const"}),
            af.tool_result(now - timedelta(minutes=20, seconds=i),
                           f"call_s{i}", stdout=f"14 matches ({desc})"),
        ], mtime=now - timedelta(minutes=20))
        _write_json(sub_dir / f"{stem}.meta.json", {
            "agentType": agent_type, "description": desc,
            "toolUseId": f"call_d{i}", "spawnDepth": 1,
        }, mtime=now)

    wf_dir = sub_dir / "workflows" / f"wf_{rng.getrandbits(48):012x}"
    _write_jsonl(wf_dir / "journal.jsonl", [
        {"type": "started", "key": "v2:aa", "agentId": "agent-x1"},
        {"type": "result", "key": "v2:aa", "agentId": "agent-x1"},
    ], mtime=now - timedelta(minutes=15))
    return sid


def messy(dest: Path, now: datetime, rng: random.Random) -> str:
    """A session full of hostile lines: giant attachment, broken JSON,
    empty neighbour file."""
    sid = _rand_sid(rng)
    f = LineFactory(sid)
    lines = [
        f.user_prompt(now - timedelta(hours=5), "Import this dataset"),
        f.tool_call(now - timedelta(hours=5, seconds=5), "call_e1",
                    "Read", {"file_path": "data/big.csv"}),
        f.tool_result(now - timedelta(hours=5, seconds=6), "call_e1",
                      stdout="(truncated)"),
    ]
    path = dest / DEMO_PROJECT_DIR / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for obj in lines:
            fh.write(json.dumps(obj) + "\n")
        fh.write('{"type":"attachment","huge":"' + "x" * (6 * 1024 * 1024)
                 + '"}\n')        # > max_line_bytes: must be skipped
        fh.write('{"type":"assistant","message": BROKEN\n')  # bad JSON
    _backdate(path, now - timedelta(hours=5))

    empty_sid = _rand_sid(rng)
    (dest / DEMO_PROJECT_DIR / f"{empty_sid}.jsonl").touch()
    _backdate(dest / DEMO_PROJECT_DIR / f"{empty_sid}.jsonl",
              now - timedelta(days=1))
    return sid


SCENARIOS = {
    "completed": completed,
    "active": active,
    "stalled": stalled,
    "subagents": with_subagents,
    "messy": messy,
}


def make_fixture_tree(dest: Path, scenarios=("completed", "active",
                                             "stalled", "subagents",
                                             "messy"),
                      seed: int = 7,
                      now: datetime | None = None) -> dict:
    """Build a fake projects tree. Returns {scenario: session_id}."""
    now = now or datetime.now(timezone.utc)
    rng = random.Random(seed)
    sids = {}
    for name in scenarios:
        sids[name] = SCENARIOS[name](dest, now, rng)
    return sids
