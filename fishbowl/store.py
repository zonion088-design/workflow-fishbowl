"""In-memory session index.

The store is mutated only by the scanner thread and read by the HTTP
server threads, so every public method takes the lock.  Activities are
kept per session in a bounded ring (newest last); anything older is
simply forgotten - the transcript on disk remains the source of truth.

Idempotency note: Activity keys are deterministic, but we do *not*
keep a key set - memory matters more than dedup here, and the scanner
guarantees a line is emitted at most once per session lifetime (a
truncated file forces a full session rebuild, see scanner.py).
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone

from .config import Config
from .model import Activity, Session, ToolCall
from .parser import LineResult

ACTIVITY_RING = 2000


def ts_to_epoch(ts: str | None) -> float | None:
    """Best-effort ISO-8601 -> epoch seconds. None if unparseable."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(
            ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


class Store:

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._lock = threading.RLock()
        self.sessions: dict[str, Session] = {}
        self._activities: dict[str, deque[Activity]] = {}
        self._file_to_session: dict[str, str] = {}

    # ------------------------------------------------------------------
    # writes (scanner thread)

    def session_for(self, entry) -> Session:
        """Get or create the session a FileEntry belongs to."""
        sid = entry.session_id
        with self._lock:
            self._file_to_session[entry.file_id] = sid
            s = self.sessions.get(sid)
            if s is None:
                s = self.sessions[sid] = Session(
                    session_id=sid, project_dir=entry.project_dir)
                self._activities[sid] = deque(maxlen=ACTIVITY_RING)
            return s

    def apply(self, entry, line_no: int, res: LineResult) -> None:
        with self._lock:
            s = self.session_for(entry)
            if res.cwd and not s.cwd:
                s.cwd = res.cwd
            if res.git_branch and not s.git_branch:
                s.git_branch = res.git_branch
            if res.version and not s.version:
                s.version = res.version
            if res.title:
                s.title = res.title
            if res.usage:
                s.usage.add(res.usage, res.model)
                s.counts["messages"] += 1

            ring = self._activities[s.session_id]
            for act in res.activities:
                self._apply_activity(s, ring, act)

            if res.counted_as:
                s.counts[f"line_{res.counted_as}"] = \
                    s.counts.get(f"line_{res.counted_as}", 0) + 1

    def _apply_activity(self, s: Session, ring: deque, act: Activity) -> None:
        ts = ts_to_epoch(act.ts)
        if ts is not None:
            if s.started_at is None or ts < (ts_to_epoch(s.started_at)
                                             or ts):
                s.started_at = act.ts
            if s.last_activity_at is None or \
                    ts >= (ts_to_epoch(s.last_activity_at) or -1):
                s.last_activity_at = act.ts

        if act.kind == "user_prompt" and not act.sidechain \
                and not s.first_prompt:
            s.first_prompt = act.summary

        if act.kind == "tool_call" and act.tool_use_id:
            s.pending_tools[act.tool_use_id] = ToolCall(
                tool_use_id=act.tool_use_id, name=act.tool_name or "?",
                brief=act.summary, started_ts=act.started_ts or act.ts)
            s.counts["tools"] += 1

        elif act.kind == "tool_result" and act.tool_use_id:
            call = s.pending_tools.pop(act.tool_use_id, None)
            if call is not None:
                start = ts_to_epoch(call.started_ts)
                if start is not None and ts is not None and ts >= start:
                    act.duration_ms = int((ts - start) * 1000)

        if act.kind in ("tool_call", "assistant_text"):
            s.current_action = act

        if act.is_error:
            s.counts["errors"] += 1

        if act.agent and act.kind in ("tool_call", "assistant_text",
                                      "tool_result"):
            info = s.subagents.setdefault(
                act.agent, {"agent": act.agent})
            info["last_action"] = act.summary
            info["last_ts"] = act.ts

        ring.append(act)

    def touch(self, entry, size: int, mtime_ns: int) -> None:
        """Feed file stats to an *existing* session (no implicit
        creation - an empty file must not conjure a ghost session)."""
        with self._lock:
            sid = entry.session_id
            s = self.sessions.get(sid)
            if s is None:
                return
            if size > s.file_size:
                s.file_size = size
            if mtime_ns > s.last_mtime_ns:
                s.last_mtime_ns = mtime_ns
            if entry.file_id not in s.files:
                s.files.append(entry.file_id)

    def register_subagent_meta(self, sid: str, agent: str,
                               meta: dict) -> None:
        with self._lock:
            s = self.sessions.get(sid)
            if s is None:
                return
            info = s.subagents.setdefault(agent, {"agent": agent})
            info.update({k: v for k, v in meta.items() if v is not None})

    def drop_session(self, sid: str) -> None:
        with self._lock:
            self.sessions.pop(sid, None)
            self._activities.pop(sid, None)
            for fid in [f for f, s in self._file_to_session.items()
                        if s == sid]:
                del self._file_to_session[fid]

    # ------------------------------------------------------------------
    # reads (server threads)

    def get(self, sid: str) -> Session | None:
        with self._lock:
            return self.sessions.get(sid)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [s.to_dict() for s in self.sessions.values()]

    def activities(self, sid: str, before_key: str | None = None,
                   limit: int = 500) -> dict:
        """Activities for one session, oldest first (newest last).

        Without ``before_key``: the newest ``limit`` items.  With
        ``before_key``: the ``limit`` items immediately preceding that
        key - i.e. "load older".  ``next`` is the key to continue
        paginating (None when the ring start is reached).
        """
        with self._lock:
            ring = self._activities.get(sid)
            if ring is None:
                return {"items": [], "next": None}
            items = [a.to_dict() for a in ring]
            keys = [a.key for a in ring]

            if not before_key:
                window = items[-limit:] if limit and len(items) > limit \
                    else items
                more = len(items) > len(window)
            else:
                try:
                    idx = keys.index(before_key)
                except ValueError:
                    return {"items": [], "next": None}
                start = max(0, idx - limit) if limit else 0
                window = items[start:idx]
                more = start > 0
                if not window:
                    return {"items": [], "next": None}

            nxt = window[0]["key"] if window and more else None
            return {"items": window, "next": nxt}
