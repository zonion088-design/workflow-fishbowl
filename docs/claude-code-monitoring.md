# Claude Code monitoring

workflow-fishbowl observes Claude Code JSONL transcripts under:

- `~/.claude/projects/`

It shows projects and sessions, current tool calls, prompts, assistant output,
subagents, errors, activity timing, token usage, and estimated cost. Scanning
is incremental and preserves byte-offset cursors so large transcript histories
do not need to be reparsed on every poll.

The transcript root is read-only. The only optional state written by the
application is its own cursor cache at `~/.fishbowl/state.json`.
