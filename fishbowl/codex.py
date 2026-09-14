"""Codex rollout discovery and parsing."""
from __future__ import annotations

import json
from pathlib import Path

from .model import Activity
from .parser import (
    LineContext, LineResult, KIND_ASSISTANT_TEXT, KIND_THINKING,
    KIND_TOOL_CALL, KIND_TOOL_RESULT, KIND_USER_PROMPT, _clip,
)
from .scanner import FileEntry


class CodexAdapter:
    name = "codex"

    def __init__(self, root: Path):
        self.root = Path(root)

    def discover(self):
        entries = []
        if not self.root.is_dir():
            return entries, []
        for path in sorted(self.root.rglob("*.jsonl")):
            sid, project = path.stem, "codex"
            try:
                with path.open(encoding="utf-8", errors="replace") as f:
                    first = json.loads(f.readline())
                payload = first.get("payload") or {}
                sid = payload.get("session_id") or payload.get("id") or sid
                cwd = payload.get("cwd")
                if cwd:
                    project = Path(cwd).name or str(cwd)
            except (OSError, ValueError):
                pass
            entries.append(FileEntry(
                file_id="codex/" + path.relative_to(self.root).as_posix(),
                path=path, session_id=str(sid), project_dir=project,
                format="codex"))
        return entries, []

    def meta_entry(self, meta_path):
        return None


class MultiAdapter:
    name = "claude-code+codex"

    def __init__(self, adapters):
        self.adapters = adapters

    def discover(self):
        entries, metas = [], []
        for adapter in self.adapters:
            found, metadata = adapter.discover()
            entries.extend(found)
            metas.extend(metadata)
        return entries, metas

    def meta_entry(self, meta_path):
        for adapter in self.adapters:
            entry = adapter.meta_entry(meta_path)
            if entry is not None:
                return entry
        return None


def _activity(ctx, ts, kind, summary, **kwargs):
    return Activity(key=f"{ctx.file_id}:{ctx.line_no}", ts=ts or "",
                    kind=kind, summary=_clip(summary or "", ctx.preview_chars),
                    **kwargs)


def _message_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(x.get("text") or x.get("input_text") or
                            x.get("output_text") or "")
                        for x in content if isinstance(x, dict)).strip()
    return ""


def parse_codex_line(obj: dict, ctx: LineContext) -> LineResult:
    res = LineResult()
    ts = obj.get("timestamp") or ctx.fallback_ts
    outer = obj.get("type")
    p = obj.get("payload") or {}
    kind = p.get("type")

    if outer == "session_meta":
        res.cwd = p.get("cwd")
        res.version = p.get("cli_version")
    elif outer == "turn_context":
        res.cwd = p.get("cwd")
        res.model = p.get("model")
    elif outer == "event_msg" and kind == "user_message":
        text = p.get("message") or ""
        if text:
            res.activities.append(_activity(ctx, ts, KIND_USER_PROMPT, text))
    elif outer == "event_msg" and kind == "agent_message":
        text = p.get("message") or ""
        if text:
            res.activities.append(_activity(ctx, ts, KIND_ASSISTANT_TEXT, text))
    elif outer == "event_msg" and kind == "agent_reasoning":
        text = p.get("text") or ""
        if text:
            res.activities.append(_activity(ctx, ts, KIND_THINKING, text))
    elif outer == "response_item" and kind == "message":
        text = _message_text(p.get("content"))
        role = p.get("role")
        if text and role == "user":
            res.activities.append(_activity(ctx, ts, KIND_USER_PROMPT, text))
        elif text and role == "assistant":
            res.activities.append(_activity(ctx, ts, KIND_ASSISTANT_TEXT, text))
    elif outer == "response_item" and kind in ("function_call", "custom_tool_call"):
        name = p.get("name") or p.get("namespace") or "tool"
        raw = p.get("arguments") or p.get("input") or ""
        res.activities.append(_activity(
            ctx, ts, KIND_TOOL_CALL, f"{name}: {raw}", tool_name=name,
            tool_use_id=p.get("call_id") or p.get("id"), started_ts=ts))
    elif outer == "response_item" and kind in (
            "function_call_output", "custom_tool_call_output"):
        output = p.get("output") or "done"
        res.activities.append(_activity(
            ctx, ts, KIND_TOOL_RESULT, str(output),
            tool_use_id=p.get("call_id") or p.get("id")))
    elif outer == "token_usage_record":
        usage = p.get("usage") or p.get("turn_token_usage") or {}
        res.usage = {
            "input_tokens": usage.get("input_tokens", 0),
            "cache_read_input_tokens": usage.get("cached_input_tokens", 0),
            "cache_creation_input_tokens": 0,
            "output_tokens": usage.get("output_tokens", 0),
        }
    else:
        res.counted_as = f"codex_{outer}_{kind}"
    return res
