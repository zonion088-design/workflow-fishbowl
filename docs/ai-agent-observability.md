# AI agent observability

AI coding agents are productive but difficult to supervise during long runs.
workflow-fishbowl provides a local observability layer for Codex and Claude
Code without becoming a remote logging service.

The dashboard focuses on four questions:

1. Which sessions are active, idle, stalled, or archived?
2. What tool call or agent step is currently running?
3. What happened in the activity timeline?
4. How much model usage and estimated cost has accumulated?

All bundled fixtures and the interactive workbench demo use synthetic data.
