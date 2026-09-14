"""Session status classification - pure logic, injected clock.

active   - something happened within ``idle_seconds``
idle     - quiet for a few minutes, but recent enough to matter
stalled  - a tool call has been hanging past ``stall_tool_seconds``
           AND the session's files have been silent just as long
           (both conditions - a live file means the agent is still
           working, which is *not* stalled). Only meaningful while
           the session is still inside the recent window; an old
           interrupted session is simply archived, not "stalled".
archived - nothing for a long time
"""
from __future__ import annotations

from .config import Config
from .model import Session
from .store import ts_to_epoch

STATUS_ACTIVE = "active"
STATUS_IDLE = "idle"
STATUS_STALLED = "stalled"
STATUS_ARCHIVED = "archived"


def classify(s: Session, cfg: Config, now: float) -> str:
    last_ts = ts_to_epoch(s.last_activity_at)
    if last_ts is None:
        # no timestamps at all - fall back to file mtime
        last_ts = s.last_mtime_ns / 1e9 if s.last_mtime_ns else 0
        if last_ts == 0:
            return STATUS_ARCHIVED

    age = now - last_ts

    if age <= cfg.idle_seconds:
        return STATUS_ACTIVE

    if age <= cfg.active_window_minutes * 60:
        if s.pending_tools:
            oldest = min(
                (ts_to_epoch(t.started_ts) or 0) for t in
                s.pending_tools.values())
            pending_age = now - oldest
            file_age = now - (s.last_mtime_ns / 1e9 if s.last_mtime_ns
                              else 0)
            if pending_age > cfg.stall_tool_seconds \
                    and file_age > cfg.stall_tool_seconds:
                return STATUS_STALLED
        return STATUS_IDLE

    return STATUS_ARCHIVED
