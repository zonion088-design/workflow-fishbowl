# Codex monitoring

workflow-fishbowl can observe local Codex rollout JSONL files from:

- `~/.codex/sessions/`
- `~/.codex/archived_sessions/`

The Codex adapter recognizes user messages, assistant messages, reasoning
events, tool calls, tool results, session metadata, and token usage records.
It converts them into the same dashboard model used for Claude Code sessions.

This is a local observer: it does not modify Codex sessions or send transcript
data over the network.
