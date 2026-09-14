"""Scanner tests: incremental reads, half-lines, idempotency, truncation."""
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fishbowl.fixtures_gen import make_fixture_tree, DEMO_PROJECT_DIR

from fishbowl.app import App
from fishbowl.config import Config

NOW = datetime.now(timezone.utc)


def make_app(tmp: Path) -> tuple[App, dict]:
    sids = make_fixture_tree(tmp, now=NOW)
    cfg = Config(source_root=tmp, cache_path=None)
    return App(cfg), sids


class ScanOnceTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.app, self.sids = make_app(self.tmp)
        self.stats = self.app.scan_once()

    def test_all_sessions_found(self):
        self.assertEqual(len(self.app.store.sessions), 5)

    def test_stalled_session(self):
        s = self.app.store.get(self.sids["stalled"])
        self.assertEqual(len(s.pending_tools), 1)
        self.assertIn("curl", list(s.pending_tools.values())[0].brief)

    def test_active_session_pending(self):
        s = self.app.store.get(self.sids["active"])
        self.assertEqual(len(s.pending_tools), 1)
        self.assertEqual(s.pending_tools.popitem()[1].name, "Bash")

    def test_completed_no_pending(self):
        s = self.app.store.get(self.sids["completed"])
        self.assertEqual(len(s.pending_tools), 0)
        self.assertEqual(s.title, "Rate limiter for API client")

    def test_subagents_registered(self):
        s = self.app.store.get(self.sids["subagents"])
        self.assertEqual(len(s.subagents), 2)
        kinds = {info.get("agent_type") for info in s.subagents.values()}
        self.assertEqual(kinds, {"Explore", "general-purpose"})

    def test_messy_lines_skipped_and_errors_counted(self):
        self.assertGreaterEqual(self.stats.lines_skipped, 1)
        self.assertGreaterEqual(self.stats.parse_errors, 1)
        s = self.app.store.get(self.sids["messy"])
        self.assertEqual(len(s.pending_tools), 0)   # result line parsed

    def test_oversized_line_not_parsed(self):
        s = self.app.store.get(self.sids["messy"])
        # only the 3 real lines produced activities (2 prompts-ish + tools)
        ring = self.app.store.activities(s.session_id)["items"]
        self.assertLessEqual(len(ring), 4)


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.app, self.sids = make_app(self.tmp)
        self.app.scan_once()

    def _session_file(self, name) -> Path:
        sid = self.sids[name]
        return self.tmp / DEMO_PROJECT_DIR / f"{sid}.jsonl"

    def test_no_change_zero_work(self):
        stats = self.app.scan_once()
        self.assertEqual(stats.lines_parsed, 0)
        self.assertEqual(stats.files_changed, 0)

    def test_increment_only_new_line(self):
        f = self._session_file("completed")
        line = json.dumps({"type": "user", "timestamp":
                           NOW.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                           "message": {"content": "one more thing"}})
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        stats = self.app.scan_once()
        self.assertEqual(stats.lines_parsed, 1)
        s = self.app.store.get(self.sids["completed"])
        ring = self.app.store.activities(s.session_id)["items"]
        self.assertEqual(ring[-1]["summary"], "one more thing")

    def test_half_line_not_consumed(self):
        f = self._session_file("completed")
        with open(f, "a", encoding="utf-8") as fh:
            fh.write('{"type":"user","mess')     # no trailing newline
        stats = self.app.scan_once()
        self.assertEqual(stats.lines_parsed, 0)
        # complete the line -> parsed exactly once
        with open(f, "a", encoding="utf-8") as fh:
            fh.write('age":{"content":"completed line"}}\n')
        stats = self.app.scan_once()
        self.assertEqual(stats.lines_parsed, 1)

    def test_truncation_rebuilds_without_duplicates(self):
        s = self.app.store.get(self.sids["completed"])
        tokens_before = s.usage.input_tokens
        f = self._session_file("completed")
        lines = f.read_text(encoding="utf-8").splitlines(keepends=True)
        with open(f, "w", encoding="utf-8") as fh:
            fh.writelines(lines[:3])            # cut the file short
        os.utime(f, None)
        self.app.scan_once()                    # detect + start rebuild
        self.app.scan_once()                     # finish rebuild
        self.assertIn(self.sids["completed"], self.app.store.sessions)
        s2 = self.app.store.get(self.sids["completed"])
        # 3 lines worth of usage, no double counting
        self.assertLessEqual(s2.usage.input_tokens, tokens_before)
        self.assertGreater(s2.usage.input_tokens, 0)


class CursorStateTests(unittest.TestCase):
    def test_save_load_roundtrip(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        state = tmp / "state.json"
        sids = make_fixture_tree(tmp, now=NOW)

        def fresh_app():
            cfg = Config(source_root=tmp, cache_path=None)
            return App(cfg)

        app = fresh_app()
        app.scan_once()
        app.scanner.save_state(state)
        offsets = {k: c.offset for k, c in
                   app.scanner._cursors.items()}

        app2 = fresh_app()
        app2.scanner.load_state(state)
        for fid, cur in app2.scanner._cursors.items():
            self.assertEqual(cur.offset, offsets[fid])
        # rescan with restored cursors: nothing new
        stats = app2.scan_once()
        self.assertEqual(stats.lines_parsed, 0)


if __name__ == "__main__":
    unittest.main()
