"""Source adapters.

A source adapter turns a directory tree of agent transcripts into
FileEntries the scanner understands.  v0.1 ships ClaudeCodeAdapter;
the Protocol is the extension point for other agents (Codex, ...)
and for the demo fixtures (which reuse the same adapter pointed at
a different root).
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .scanner import FileEntry


class SourceAdapter(Protocol):
    name: str

    def discover(self) -> tuple[list[FileEntry], list[Path]]:
        """Return (transcript entries, metadata files)."""

    def meta_entry(self, meta_path: Path) -> FileEntry | None:
        """Map a metadata file back to its session/agent entry."""
