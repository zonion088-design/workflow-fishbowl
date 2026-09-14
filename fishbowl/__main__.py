"""CLI entry point.

    python -m fishbowl                 # watch Codex + Claude Code
    python -m fishbowl --demo          # synthetic data, no agent needed
    python -m fishbowl --port 8765
    python -m fishbowl --root PATH     # custom transcript root
    python -m fishbowl --dump          # one scan, JSON to stdout, exit
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

# Windows consoles default to a legacy codepage; force UTF-8 so dumps
# of arbitrary transcript text never crash on print.
if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")

from . import __version__
from .app import App, build_app
from .config import Config, load_prices

PKG_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = Path.home() / ".claude" / "projects"
HOST = "127.0.0.1"          # non-negotiable: localhost only


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fishbowl",
        description="Watch Codex and Claude Code workflows through the glass "
                    "- a read-only local observability dashboard.")
    p.add_argument("--demo", action="store_true",
                   help="run on bundled synthetic data (no Codex or Claude "
                        "needed; nothing in the repo is modified)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--root", type=Path, default=None,
                   help="transcript root to watch "
                        "(default: ~/.claude/projects)")
    p.add_argument("--no-cache", action="store_true",
                   help="do not persist scan cursors between runs")
    p.add_argument("--poll", type=float, default=2.0,
                   help="scan interval in seconds (default 2)")
    p.add_argument("--open", action="store_true",
                   help="open the dashboard in a browser")
    p.add_argument("--dump", action="store_true",
                   help="scan once, print a JSON snapshot, exit")
    p.add_argument("--version", action="version",
                   version=f"fishbowl {__version__}")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.demo:
        # prepare_demo() generates a fresh tree in a temp dir and swaps
        # source_root, so this placeholder just needs to exist.
        root = Path.home() / ".claude" / "projects"
        cache = None
    else:
        root = args.root or DEFAULT_ROOT
        cache = None if args.no_cache \
            else Path.home() / ".fishbowl" / "state.json"

    cfg = Config(
        source_root=root, port=args.port, poll_interval=args.poll,
        cache_path=cache, prices=load_prices(PKG_DIR / "prices.json"),
        include_codex=not args.demo)

    app: App = build_app(cfg, demo=args.demo)

    if args.dump:
        import json
        app.scan_once()
        print(json.dumps(app.snapshot(), indent=2, ensure_ascii=False))
        return 0

    try:
        app.run(open_browser=args.open)
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
