# fishbowl 🐠

**Watch your Claude Code agents through the glass.**

fishbowl is a tiny, read-only local dashboard that shows what your Claude Code
sessions are doing *right now* — and what they did while you were looking
away. If you have ever left a long agent task running in a terminal, come
back 20 minutes later and wondered *"what is it actually doing?"*, fishbowl
is for you.

- **Live session list** — every project you work on, grouped, with status
  (active / idle / stalled / archived), the current tool call, and how long
  it has been running.
- **Stall detection** — a tool call that has been pending for 5 minutes with
  a silent transcript gets a red badge. No more guessing whether the agent
  hung or is just thinking hard.
- **Activity timeline** — the full story of a session: prompts, thinking,
  tool calls with durations, errors, subagents.
- **Token & cost stats** — usage by model, per-session cost *estimates* from
  an editable price table.
- **Zero dependencies. No install. Read-only.**

fishbowl works by tailing the JSONL transcripts that Claude Code already
writes under `~/.claude/projects/`. It never talks to the network, never
sends telemetry, and never writes a single byte into your `~/.claude`
directory.

## Quick start

Requires Python 3.10+. No pip packages — fishbowl is pure standard library.

```bash
git clone https://github.com/zonion088-design/fishbowl.git
cd fishbowl
python -m fishbowl
```

Then open <http://127.0.0.1:8765>. That's it.

Prefer a real install?

```bash
pipx install .
fishbowl            # same thing, on your PATH
```

## Demo mode

No Claude Code on this machine? Try the demo — it generates synthetic
sessions (including a deliberately stalled one) and replays a scripted
agent in real time:

```bash
python -m fishbowl --demo
```

## How it works

```
~/.claude/projects/          fishbowl                          you
┌─────────────────┐    ┌──────────────────────────────┐    ┌─────────┐
│ <project>/      │    │ scanner (incremental,        │    │ browser │
│   <session>.jsonl├───►│   byte-offset cursors)      │    │         │
│   <session>/    │    │   → parser → in-memory store │───►│ 127.0.0.│
│     subagents/… │    │   → read-only GET API        │    │  :8765   │
└─────────────────┘    └──────────────────────────────┘    └─────────┘
        read-only                  localhost only
```

- **Incremental scanning** — files are `stat()`ed every 2 seconds; only new
  bytes are read and parsed. A multi-hundred-MB transcript history is fine;
  restarts resume from persisted cursors (`~/.fishbowl/state.json`).
- **Half-line safe** — a line that Claude Code is still writing is left for
  the next cycle. Truncated/replaced files are detected and rebuilt.
- **Hostile-input safe** — corrupted JSON, 6 MB attachment lines and empty
  files are skipped or flagged, never crash the scanner.
- **Deterministic keys** — every activity has a stable `file:line` key, so
  rescans are idempotent.

## Configuration

```text
usage: fishbowl [-h] [--demo] [--port PORT] [--root PATH] [--no-cache]
                [--poll POLL] [--open] [--dump] [--version]
```

| Flag | Default | Meaning |
|---|---|---|
| `--demo` | off | run on bundled synthetic data |
| `--port` | 8765 | dashboard port (localhost only) |
| `--root` | `~/.claude/projects` | transcript root to watch |
| `--no-cache` | off | don't persist scan cursors between runs |
| `--poll` | 2.0 | scan interval in seconds |
| `--open` | off | open the dashboard in a browser on start |
| `--dump` | off | scan once, print JSON snapshot, exit (debugging) |

**Prices**: cost figures are *estimates* from
[fishbowl/prices.json](fishbowl/prices.json).
Every model there is approximate — edit the file freely; unknown models show
"—" instead of a wrong number.

**Thresholds**: "stalled" = a tool call pending > 300 s *and* the session
files silent for > 300 s; "idle" = no activity for 180 s; sessions older
than 30 min without activity are archived. These are constants in
[fishbowl/config.py](fishbowl/config.py) — tweak and go.

## Privacy & security

- **Read-only by construction.** fishbowl opens your transcripts in read
  mode. The HTTP server answers GET only — POST/PUT/DELETE/PATCH return
  `405 read-only service`.
- **Loopback only.** The server binds `127.0.0.1`, hard-coded. There is no
  `--host` flag on purpose. No auth needed because nothing outside your
  machine can reach it.
- **Zero telemetry.** No network calls, no analytics, no crash reporting.
  The only file fishbowl writes is its own cursor cache.
- **Be aware**: transcripts contain your real source code, prompts and
  possibly secrets. fishbowl displays them locally — don't screenshot them
  into public places blindly. (The bundled fixtures and demo data are fully
  synthetic.)

## FAQ

**Does it modify Claude Code or my sessions?**
No. fishbowl is a pure observer.

**Windows / macOS / Linux?**
Yes — stdlib only, no OS-specific code. (Developed and tested on Windows.)

**Does it send my transcripts anywhere?**
No. There is no outbound networking code at all.

**Where are my older sessions?**
Sessions with no activity in the last 30 minutes are grouped under
"archived" — still browsable, just out of the way.

**Will it read huge transcripts?**
Yes — incrementally. First scan of a big history takes a moment; afterwards
only new bytes are parsed.

## Roadmap

- [ ] v0.2: supervision features — approvals, notifications
- [ ] Codex adapter (same dashboard, `.codex` sessions) — the source layer
      is already an adapter protocol
- [ ] SSE push instead of polling
- [ ] Docker image
- [ ] Timeline filtering / search

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The one hard rule: **this repo
never contains real transcripts** — fixtures are generated by
[fishbowl/fixtures_gen.py](fishbowl/fixtures_gen.py).

## License

[MIT](LICENSE)
