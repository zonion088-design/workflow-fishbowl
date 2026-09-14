"""Runtime configuration and model pricing."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    source_root: Path                       # ~/.claude/projects or fixtures
    port: int = 8765
    poll_interval: float = 2.0               # seconds between scans
    stall_tool_seconds: int = 300            # hung tool call threshold
    idle_seconds: int = 180                  # "recent" window
    active_window_minutes: int = 30          # beyond this -> archived
    preview_chars: int = 400                  # summaries are clipped to this
    max_line_bytes: int = 5_000_000          # giant attachment lines: skip
    cache_path: Path | None = None           # None -> no cursor persistence
    prices: list = field(default_factory=list)  # from prices.json


def load_prices(path: Path) -> list:
    """Load the pricing table. Missing file -> empty (costs hidden)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("models", [])
    except (OSError, ValueError):
        return []


def cost_for(prices: list, model: str | None,
             usage: dict) -> float | None:
    """Estimated USD cost of a usage bucket, or None if the model is
    unknown. Values are rough by design - the table ships approximate
    defaults and users are expected to edit it."""
    if not model:
        return None
    m = model.lower()
    for entry in prices:
        if entry.get("match") and entry["match"] in m:
            cost = (
                usage.get("input_tokens", 0) / 1e6 * entry["in"]
                + usage.get("output_tokens", 0) / 1e6 * entry["out"]
                + usage.get("cache_read_tokens", 0) / 1e6
                * entry.get("cache_read", 0.1)
                + usage.get("cache_write_tokens", 0) / 1e6
                * entry.get("cache_write", 0.1)
            )
            return round(cost, 4)
    return None
