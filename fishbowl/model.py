"""Domain model for fishbowl.

Everything the dashboard knows about a session is built from these
objects.  They are plain dataclasses on purpose: easy to serialize,
easy to test, no ORM, no database.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class TokenUsage:
    """Accumulated token usage for one session (or one global bucket)."""

    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    output_thinking_tokens: int = 0
    # model name -> number of assistant turns seen with that model
    models: Counter = field(default_factory=Counter)

    def add(self, usage: dict, model: str | None) -> None:
        self.input_tokens += _i(usage.get("input_tokens"))
        self.cache_read_tokens += _i(usage.get("cache_read_input_tokens"))
        self.cache_write_tokens += _i(usage.get("cache_creation_input_tokens"))
        self.output_tokens += _i(usage.get("output_tokens"))
        od = usage.get("output_tokens_details") or {}
        self.output_thinking_tokens += _i(od.get("thinking_tokens"))
        self.models[model or "unknown"] += 1

    @property
    def total(self) -> int:
        return (self.input_tokens + self.cache_read_tokens
                + self.cache_write_tokens + self.output_tokens)

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "output_tokens": self.output_tokens,
            "output_thinking_tokens": self.output_thinking_tokens,
            "models": dict(self.models),
        }


def _i(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


@dataclass
class Activity:
    """One human-readable line in a session timeline.

    The key is a deterministic primary key ("<file_id>:<line_no>"):
    re-parsing the same line must be a no-op (idempotent upsert).
    """

    key: str
    ts: str                      # ISO-8601 from the transcript line
    kind: str                    # user_prompt|assistant_text|thinking|tool_call|
                                # tool_result|workflow|queue|parse_error
    summary: str = ""            # one-line human summary (previews truncated)
    tool_name: str | None = None
    tool_use_id: str | None = None   # links tool_call <-> tool_result
    started_ts: str | None = None     # tool_call only: when the call started
    duration_ms: int | None = None    # tool_result only: paired call duration
    is_error: bool = False
    sidechain: bool = False      # subagent / background activity
    agent: str | None = None     # subagent file stem, e.g. "agent-a33..."

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "ts": self.ts,
            "kind": self.kind,
            "summary": self.summary,
            "tool_name": self.tool_name,
            "tool_use_id": self.tool_use_id,
            "duration_ms": self.duration_ms,
            "is_error": self.is_error,
            "sidechain": self.sidechain,
            "agent": self.agent,
        }


@dataclass
class ToolCall:
    """A pending (not yet answered) tool call - the heart of "what is
    the agent doing right now"."""

    tool_use_id: str
    name: str
    brief: str
    started_ts: str

    def to_dict(self) -> dict:
        return {
            "tool_use_id": self.tool_use_id,
            "name": self.name,
            "brief": self.brief,
            "started_ts": self.started_ts,
        }


@dataclass
class Session:
    """Everything known about one Codex or Claude Code session."""

    session_id: str
    project_dir: str             # encoded directory name, e.g. "C--Users-demo-x"

    # filled in as lines are parsed
    cwd: str | None = None
    title: str | None = None     # ai-title > summary > first prompt > sid[:8]
    first_prompt: str | None = None
    started_at: str | None = None
    last_activity_at: str | None = None
    version: str | None = None
    git_branch: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    counts: Counter = field(default_factory=Counter)

    # runtime state maintained by the store
    status: str = "archived"     # recomputed dynamically, never persisted
    pending_tools: dict[str, ToolCall] = field(default_factory=dict)
    current_action: Activity | None = None
    subagents: dict[str, dict] = field(default_factory=dict)  # stem -> meta
    file_size: int = 0            # max size among the session's files
    last_mtime_ns: int = 0        # max mtime among the session's files
    files: list[str] = field(default_factory=list)

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.first_prompt:
            return self.first_prompt[:80]
        return self.session_id[:8]

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "project_dir": self.project_dir,
            "cwd": self.cwd,
            "title": self.display_title,
            "started_at": self.started_at,
            "last_activity_at": self.last_activity_at,
            "version": self.version,
            "git_branch": self.git_branch,
            "status": self.status,
            "current_action": (self.current_action.to_dict()
                               if self.current_action else None),
            "pending_tools": [t.to_dict() for t in
                              self.pending_tools.values()],
            "usage": self.usage.to_dict(),
            "counts": dict(self.counts),
            "subagents": list(self.subagents.values()),
            "file_size": self.file_size,
        }
