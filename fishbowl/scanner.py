"""Incremental transcript scanner - the engine room.

Design invariants
-----------------
* Transcripts are append-only JSONL.  We remember a byte offset per
  file and only ever consume up to the last *complete* newline in the
  freshly read chunk - a half-written line stays for the next cycle.
* ``line_no`` counts complete lines from the start of the file, so
  Activity keys ("file_id:line_no") are deterministic across restarts
  with or without a cursor cache.
* If a file shrinks (truncated/replaced) we rebuild the whole session:
  drop aggregates, zero every cursor of that session, rescan next cycle.
  This keeps token/usage counters from double-counting.
* A single huge line (an attachment can inline megabytes) is counted
  and skipped, never parsed.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .model import Activity
from .parser import LineContext, LineResult, parse_line, KIND_PARSE_ERROR
from .store import Store

# do not read more than this many bytes from one file per cycle
MAX_READ_PER_CYCLE = 32 * 1024 * 1024


@dataclass
class FileEntry:
    file_id: str               # source-root-relative posix path
    path: Path
    session_id: str
    project_dir: str = ""      # encoded project directory name
    role: str = "main"         # main | subagent | workflow
    agent: str | None = None   # subagent stem, e.g. "agent-a33..."
    format: str = "claude"     # claude | codex


@dataclass
class ScanStats:
    files_watched: int = 0
    files_changed: int = 0
    bytes_read: int = 0
    lines_parsed: int = 0
    lines_skipped: int = 0     # oversized lines
    parse_errors: int = 0
    sessions_dropped: int = 0
    duration_ms: int = 0


@dataclass
class _Cursor:
    offset: int = 0
    line_no: int = 0


class Scanner:
    """One instance owns the scan loop state; call scan_once() from a
    background thread every poll_interval seconds."""

    def __init__(self, adapter, store: Store, cfg: Config,
                 clock=time.time):
        self.adapter = adapter
        self.store = store
        self.cfg = cfg
        self.clock = clock
        self._cursors: dict[str, _Cursor] = {}
        self.first_pass_done = False
        self.last_stats: ScanStats = ScanStats()

    # ------------------------------------------------------------------

    def scan_once(self) -> ScanStats:
        t0 = time.perf_counter()
        stats = ScanStats()
        entries, metas = self.adapter.discover()
        stats.files_watched = len(entries)

        by_session: dict[str, list[FileEntry]] = {}
        for e in entries:
            by_session.setdefault(e.session_id, []).append(e)

        for meta_path in metas:
            self._load_meta(meta_path, stats)

        for e in entries:
            try:
                st = e.path.stat()
            except OSError:
                continue
            cur = self._cursors.get(e.file_id)
            if cur is None:
                cur = self._cursors[e.file_id] = _Cursor()

            if st.st_size < cur.offset:
                # truncated or replaced: rebuild the whole session.
                # Other files of the session get zeroed cursors and are
                # fully re-read (those already passed in this loop:
                # next cycle).  This file is re-read right now.
                self.store.drop_session(e.session_id)
                stats.sessions_dropped += 1
                for e2 in by_session.get(e.session_id, ()):
                    self._cursors[e2.file_id] = _Cursor()
                cur = self._cursors[e.file_id]

            if st.st_size > cur.offset:
                self._read_increment(e, cur, st, stats)
                stats.files_changed += 1

            self.store.touch(e, st.st_size, st.st_mtime_ns)

        stats.duration_ms = int((time.perf_counter() - t0) * 1000)
        self.last_stats = stats
        self.first_pass_done = True
        return stats

    # ------------------------------------------------------------------

    def _read_increment(self, e: FileEntry, cur: _Cursor, st, stats):
        want = st.st_size - cur.offset
        try:
            with open(e.path, "rb") as f:
                f.seek(cur.offset)
                chunk = f.read(min(want, MAX_READ_PER_CYCLE))
        except OSError:
            return
        if not chunk:
            return

        end = chunk.rfind(b"\n")
        if end == -1:
            # no complete line in this chunk yet; if what we have is one
            # absurdly large line and the file is fully read, skip it
            if len(chunk) > self.cfg.max_line_bytes and len(chunk) == want:
                cur.offset = st.st_size
                cur.line_no += 1
                stats.lines_skipped += 1
            return

        consumed = chunk[:end + 1]
        fallback_ts = _iso_from_ns(st.st_mtime_ns)
        ctx = LineContext(
            file_id=e.file_id, line_no=0, session_id=e.session_id,
            role=e.role, agent=e.agent, fallback_ts=fallback_ts,
            preview_chars=self.cfg.preview_chars)

        for raw in consumed.split(b"\n")[:-1]:
            cur.line_no += 1
            if len(raw) > self.cfg.max_line_bytes:
                stats.lines_skipped += 1
                continue
            ctx.line_no = cur.line_no
            try:
                obj = json.loads(raw.decode("utf-8", errors="replace"))
                if e.format == "codex":
                    from .codex import parse_codex_line
                    res = parse_codex_line(obj, ctx)
                else:
                    res = parse_line(obj, ctx)
            except Exception:
                stats.parse_errors += 1
                res = LineResult()
                res.activities = [Activity(
                    key=f"{e.file_id}:{cur.line_no}", ts=fallback_ts,
                    kind=KIND_PARSE_ERROR, summary="unreadable line",
                    sidechain=True)]
            self.store.apply(e, cur.line_no, res)
            stats.lines_parsed += 1

        cur.offset += len(consumed)
        stats.bytes_read += len(consumed)

    def _load_meta(self, meta_path: Path, stats: ScanStats) -> None:
        """subagents/<stem>.meta.json -> session.subagents registry."""
        try:
            entry = self.adapter.meta_entry(meta_path)
            if entry is None:
                return
            obj = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        # make sure the session exists before registering into it
        # (metas are processed before their transcript lines)
        self.store.session_for(entry)
        self.store.register_subagent_meta(
            entry.session_id, entry.agent,
            {"agent_type": obj.get("agentType"),
             "description": obj.get("description"),
             "spawn_depth": obj.get("spawnDepth")})

    # ------------------------------------------------------------------
    # cursor persistence

    def save_state(self, path: Path) -> None:
        data = {fid: [c.offset, c.line_no]
                for fid, c in self._cursors.items()}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def load_state(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for fid, v in data.items():
            if isinstance(v, list) and len(v) == 2:
                self._cursors[fid] = _Cursor(int(v[0]), int(v[1]))


def _iso_from_ns(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)\
        .strftime("%Y-%m-%dT%H:%M:%S.000Z")
