"""Transcript line parsing - pure functions, no IO.

Claude Code writes one JSON object per line into
``~/.claude/projects/<encoded-dir>/<sessionId>.jsonl``.  This module
turns a decoded line into domain objects.  It never raises on odd
input: unknown line types are counted and skipped, broken values are
coerced, so one weird line can never stop the scan.

Verified line shapes (kept here as the fact sheet):

- type "assistant": message.content = [ {type: thinking|text|tool_use},
  ... ], message.usage = {input_tokens, cache_read_input_tokens,
  cache_creation_input_tokens, output_tokens, output_tokens_details:
  {thinking_tokens}}, message.model = str
- type "user": message.content is either a str (a real user prompt) or
  a list that contains tool_result blocks (tool_use_id + content);
  the user line may also carry a top-level "toolUseResult" detail
- type "queue-operation" | "attachment" | "file-history-snapshot" |
  "atis-latch" | "last-prompt" | "document" | ... : counted only
- type "ai-title": {"aiTitle": str}; type "summary": {"summary": str}
- workflow journals (subagents/workflows/wf_*/journal.jsonl):
  {"type": "started"|"result", "key": str, "agentId": str}
- common fields: timestamp (ISO-8601), cwd, sessionId, version,
  gitBranch, isSidechain, parentUuid
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .model import Activity

# kinds emitted into the timeline
KIND_USER_PROMPT = "user_prompt"
KIND_ASSISTANT_TEXT = "assistant_text"
KIND_THINKING = "thinking"
KIND_TOOL_CALL = "tool_call"
KIND_TOOL_RESULT = "tool_result"
KIND_WORKFLOW = "workflow"
KIND_QUEUE = "queue"
KIND_PARSE_ERROR = "parse_error"

# line types that only bump a counter
_COUNT_ONLY = {
    "attachment", "file-history-snapshot", "file-history-delta",
    "last-prompt", "atis-latch", "mode", "document",
}

# key preference for one-line tool-input summaries
_BRIEF_KEYS = ("command", "file_path", "pattern", "query", "path", "url",
               "prompt", "description", "skill", "notebook_path")


@dataclass
class LineContext:
    """Everything the parser needs to know about where a line lives."""

    file_id: str                 # source-root-relative posix path (idempotency key)
    line_no: int
    session_id: str
    role: str = "main"           # main | subagent | workflow
    agent: str | None = None     # subagent file stem, e.g. "agent-a33..."
    fallback_ts: str = ""        # file mtime, used if the line has no timestamp
    preview_chars: int = 400


@dataclass
class LineResult:
    """What one decoded transcript line produced."""

    activities: list[Activity] = field(default_factory=list)
    usage: dict | None = None
    model: str | None = None
    title: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    version: str | None = None
    counted_as: str | None = None   # count-only line type, if any


def parse_line(obj: dict, ctx: LineContext) -> LineResult:
    """Turn one decoded JSONL line into a LineResult. Never raises."""
    res = LineResult()
    try:
        t = obj.get("type")
        ts = obj.get("timestamp") or ctx.fallback_ts
        sidechain = bool(obj.get("isSidechain")) or ctx.role != "main"
        msg = obj.get("message") or {}

        res.cwd = obj.get("cwd")
        res.git_branch = obj.get("gitBranch")
        res.version = obj.get("version")

        if t == "assistant":
            content = msg.get("content") or []
            if isinstance(content, list):
                for block in content:
                    _assistant_block(block, ctx, ts, sidechain, res)
            res.usage = msg.get("usage") or None
            res.model = msg.get("model")

        elif t == "user":
            _user_line(obj, msg, ctx, ts, sidechain, res)

        elif t == "ai-title":
            res.title = obj.get("aiTitle")

        elif t == "summary":
            res.title = obj.get("summary")

        elif t == "queue-operation":
            res.activities.append(_act(ctx, ts, KIND_QUEUE,
                                       _brief_op(obj), sidechain=sidechain))

        elif t in ("started", "result") and ctx.role == "workflow":
            res.activities.append(
                _act(ctx, ts, KIND_WORKFLOW,
                     f"{t} agent {obj.get('agentId', '?')}",
                     sidechain=True))

        elif t in _COUNT_ONLY or t is None:
            res.counted_as = t or "unknown"

        else:
            res.counted_as = f"untyped_{t}"

    except Exception:            # absolutely never let one line kill the scan
        res.counted_as = "parse_error"
        res.activities.append(_act(ctx, ctx.fallback_ts, KIND_PARSE_ERROR,
                                   "unreadable line", sidechain=True))
    return res


# --------------------------------------------------------------------------
# user lines

def _user_line(obj, msg, ctx, ts, sidechain, res):
    content = msg.get("content")
    if isinstance(content, str):
        text = content.strip()
        if text:
            res.activities.append(
                _act(ctx, ts, KIND_USER_PROMPT, _clip(text, ctx.preview_chars),
                     sidechain=sidechain))
        return

    blocks = content if isinstance(content, list) else []
    saw_result = False
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            saw_result = True
            summary, is_error = summarize_result(
                obj.get("toolUseResult"), block, ctx.preview_chars,
                denial=obj.get("toolDenialKind"))
            res.activities.append(_act(
                ctx, ts, KIND_TOOL_RESULT, summary,
                tool_use_id=block.get("tool_use_id"),
                is_error=is_error, sidechain=sidechain, agent=ctx.agent))
    if not saw_result:
        # user text blocks without any tool_result -> treat as a prompt
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text = (block.get("text") or "").strip()
                if text:
                    res.activities.append(_act(
                        ctx, ts, KIND_USER_PROMPT,
                        _clip(text, ctx.preview_chars), sidechain=sidechain))
                break


def _assistant_block(block, ctx, ts, sidechain, res):
    if not isinstance(block, dict):
        return
    bt = block.get("type")
    if bt == "thinking":
        text = block.get("thinking") or ""
        if text.strip():
            res.activities.append(_act(
                ctx, ts, KIND_THINKING, _clip(text, ctx.preview_chars),
                sidechain=sidechain, agent=ctx.agent))
    elif bt == "text":
        text = block.get("text") or ""
        if text.strip():
            res.activities.append(_act(
                ctx, ts, KIND_ASSISTANT_TEXT, _clip(text, ctx.preview_chars),
                sidechain=sidechain, agent=ctx.agent))
    elif bt == "tool_use":
        name = block.get("name") or "?"
        res.activities.append(_act(
            ctx, ts, KIND_TOOL_CALL,
            brief_tool_input(name, block.get("input") or {},
                             ctx.preview_chars),
            tool_name=name, tool_use_id=block.get("id"),
            started_ts=ts, sidechain=sidechain, agent=ctx.agent))


# --------------------------------------------------------------------------
# summaries

def brief_tool_input(name: str, tool_input, limit: int) -> str:
    """One-line human summary of a tool call's input. Never raises."""
    brief = ""
    try:
        if isinstance(tool_input, dict):
            for key in _BRIEF_KEYS:
                if tool_input.get(key):
                    brief = str(tool_input[key])
                    break
            else:
                for v in tool_input.values():
                    if isinstance(v, (str, int, float, bool)):
                        brief = str(v)
                        break
        elif isinstance(tool_input, str):
            brief = tool_input
    except Exception:
        brief = ""
    if name.lower() == "bash" and "\n" in brief:
        brief = brief.splitlines()[0]      # just the command
    return f"{name}: {_clip(brief, limit)}" if brief else name


def summarize_result(tool_use_result, block, limit,
                     denial=None) -> tuple[str, bool]:
    """Summarize a tool result -> (summary, is_error). Never raises."""
    try:
        reason = denial or block.get("toolDenialKind")
        if block.get("is_error") or reason:
            return f"tool failed ({reason or 'error'})", True

        result = tool_use_result
        if result is None:
            result = _block_text(block)
        if result is None:
            return "done", False

        if isinstance(result, str):
            text = result.strip()
            if text.startswith("Error") or text.startswith("Interrupted"):
                return _clip(text, limit), True
            return _clip(text, limit), False

        if isinstance(result, dict):
            if "stdout" in result or "stderr" in result:
                out = (result.get("stdout") or "").strip()
                err = (result.get("stderr") or "").strip()
                if out:
                    return _clip(out.splitlines()[0], limit), False
                if err:
                    return _clip(err.splitlines()[0], limit), True
                return "done", False
            if result.get("type") in ("create", "update") and result.get("filePath"):
                return f"wrote {result['filePath']}", False
            if result.get("interrupted"):
                return "interrupted by user", True
            for key in ("description", "subject", "title", "summary"):
                if result.get(key):
                    return _clip(str(result[key]), limit), False

        return "done", False
    except Exception:
        return "unreadable result", False


def _block_text(block) -> str | None:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text") for p in content
                 if isinstance(p, dict) and p.get("type") == "text"]
        if parts:
            return "\n".join(parts)
    return None


def _brief_op(obj) -> str:
    op = obj.get("op") or obj.get("operation") or ""
    return str(op) if op else "queue operation"


def _act(ctx, ts, kind, summary, tool_name=None, tool_use_id=None,
         started_ts=None, duration_ms=None, is_error=False,
         sidechain=False, agent=None) -> Activity:
    return Activity(
        key=f"{ctx.file_id}:{ctx.line_no}",
        ts=ts or "", kind=kind,
        summary=_clip(summary, ctx.preview_chars) if summary else "",
        tool_name=tool_name, tool_use_id=tool_use_id,
        started_ts=started_ts, duration_ms=duration_ms,
        is_error=is_error, sidechain=sidechain, agent=agent)


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
