# Security policy

## Supported versions

Only the latest release on the main branch receives security fixes.

## Threat model, in short

fishbowl is a **local, read-only observer**:

- It binds `127.0.0.1` only (hard-coded; there is no `--host`).
- It serves GET only — mutating verbs return `405`.
- It makes **zero outbound network connections** (no telemetry, no updates,
  no fetches).
- It writes exactly one thing outside its own repo: its cursor cache at
  `~/.fishbowl/state.json` (disable with `--no-cache`).
- It never writes into the transcript root it watches.

The dashboard displays your transcript contents (prompts, code, tool
output) to whatever browser hits the local port. Treat a running fishbowl
like an open terminal on your machine.

## Reporting a vulnerability

Please open a GitHub security advisory (Security → Report a vulnerability)
or contact a maintainer directly. Do **not** open a public issue for
security problems. Expect a response within a few days.

When reporting, you may include synthetic reproductions (see
[fishbowl/fixtures_gen.py](fishbowl/fixtures_gen.py)) but please do not attach
real transcript files.

## Hardening notes for paranoid setups

- Run with `--no-cache` to avoid the state file entirely.
- Run with `--root` pointed at a *copy* of transcripts if you want a strict
  guarantee that not even read access touches the originals.
- Kill the process when not using it — it is a dashboard, not a daemon.
