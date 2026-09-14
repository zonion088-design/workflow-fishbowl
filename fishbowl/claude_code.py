"""Claude Code transcript adapter.

Layout under the source root (normally ``~/.claude/projects``):

    <encoded-project-dir>/<sessionId>.jsonl              main session
    <dir>/<sessionId>/subagents/agent-<id>.jsonl         subagent
    <dir>/<sessionId>/subagents/agent-<id>.meta.json     subagent meta
    <dir>/<sid>/subagents/workflows/wf-*/journal.jsonl   workflow journal
    <dir>/<sid>/subagents/workflows/wf-*/agent-*.jsonl   workflow agents

Everything else (stray json, other extensions) is ignored.
"""
from __future__ import annotations

from pathlib import Path

from .scanner import FileEntry


def _entry(root: Path, path: Path, sid: str, project_dir: str,
           role: str = "main", agent: str | None = None) -> FileEntry:
    return FileEntry(
        file_id=path.relative_to(root).as_posix(),
        path=path, session_id=sid, project_dir=project_dir,
        role=role, agent=agent)


class ClaudeCodeAdapter:
    name = "claude-code"

    def __init__(self, root: Path):
        self.root = Path(root)

    def discover(self) -> tuple[list[FileEntry], list[Path]]:
        entries: list[FileEntry] = []
        metas: list[Path] = []
        if not self.root.is_dir():
            return entries, metas

        for project in sorted(self.root.iterdir()):
            if not project.is_dir():
                continue
            for child in sorted(project.iterdir()):
                if child.is_file() and child.suffix == ".jsonl":
                    entries.append(_entry(
                        self.root, child, child.stem, project.name))
                elif child.is_dir():
                    # <project>/<sessionId>/subagents/... tree
                    sub = child / "subagents"
                    if sub.is_dir():
                        self._walk_subagents(
                            project, sub, entries, metas)
        return entries, metas

    def _walk_subagents(self, project: Path, sub: Path,
                        entries: list[FileEntry], metas: list[Path]) -> None:
        sid = sub.parent.name
        for f in sorted(sub.iterdir()):
            if f.name.endswith(".meta.json"):
                metas.append(f)
            elif f.is_file() and f.suffix == ".jsonl":
                entries.append(_entry(
                    self.root, f, sid, project.name,
                    role="subagent", agent=f.stem))
            elif f.is_dir() and f.name == "workflows":
                for wf in sorted(f.iterdir()):
                    if not wf.is_dir():
                        continue
                    for g in sorted(wf.iterdir()):
                        if not g.is_file():
                            continue
                        if g.name == "journal.jsonl":
                            entries.append(_entry(
                                self.root, g, sid, project.name,
                                role="workflow"))
                        elif g.suffix == ".jsonl":
                            entries.append(_entry(
                                self.root, g, sid, project.name,
                                role="subagent", agent=g.stem))
                        elif g.name.endswith(".meta.json"):
                            metas.append(g)

    def meta_entry(self, meta_path: Path) -> FileEntry | None:
        """agent-<id>.meta.json -> which session/agent it describes."""
        try:
            rel = meta_path.relative_to(self.root).parts
        except ValueError:
            return None
        # accepted shapes (relative to the source root):
        #   <proj>/<sid>/subagents/<stem>.meta.json
        #   <proj>/<sid>/subagents/workflows/<wf>/<stem>.meta.json
        direct = len(rel) == 4 and rel[2] == "subagents"
        nested = len(rel) == 6 and rel[2] == "subagents" \
            and rel[3] == "workflows"
        if direct or nested:
            stem = meta_path.name[:-len(".meta.json")]
            return FileEntry(
                file_id=meta_path.relative_to(self.root).as_posix(),
                path=meta_path, session_id=rel[1], project_dir=rel[0],
                role="subagent", agent=stem)
        return None
