"""Store and status classification unit tests."""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fishbowl.config import Config
from fishbowl.model import Activity, Session, ToolCall
from fishbowl.parser import LineResult
from fishbowl.status import classify
from fishbowl.store import Store, ts_to_epoch

NOW = datetime.now(timezone.utc)


def iso(dt) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class FakeEntry:
    def __init__(self, sid="s1", project="C--Users-demo-x"):
        self.file_id = f"p/{sid}.jsonl"
        self.session_id = sid
        self.project_dir = project
        self.role = "main"
        self.agent = None


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(source_root=Path("."))
        self.store = Store(self.cfg)
        self.entry = FakeEntry()

    def _result(self, **kw):
        return LineResult(**kw)

    def test_title_priority(self):
        self.store.apply(self.entry, 1, self._result(
            title="Summary title"))
        s = self.store.get("s1")
        self.assertEqual(s.title, "Summary title")
        # ai-title later replaces summary-level titles
        self.store.apply(self.entry, 2, self._result(title="AI title"))
        self.assertEqual(self.store.get("s1").title, "AI title")

    def test_first_prompt_and_display_title(self):
        act = Activity(key="p/s1.jsonl:1", ts=iso(NOW), kind="user_prompt",
                       summary="fix the bug")
        self.store.apply(self.entry, 1, self._result(activities=[act]))
        s = self.store.get("s1")
        self.assertEqual(s.first_prompt, "fix the bug")
        self.assertEqual(s.display_title, "fix the bug")
        # a title line overrides the prompt fallback
        self.store.apply(self.entry, 2, self._result(title="Bugfix"))
        self.assertEqual(s.display_title, "Bugfix")

    def test_usage_accumulates(self):
        for i in range(3):
            self.store.apply(self.entry, i + 1, self._result(
                usage={"input_tokens": 10, "cache_read_input_tokens": 100,
                       "cache_creation_input_tokens": 5,
                       "output_tokens": 7}, model="claude-sonnet-5"))
        u = self.store.get("s1").usage
        self.assertEqual(u.input_tokens, 30)
        self.assertEqual(u.cache_read_tokens, 300)
        self.assertEqual(u.output_tokens, 21)
        self.assertEqual(u.models["claude-sonnet-5"], 3)

    def test_tool_pairing_and_duration(self):
        t0 = NOW.replace(microsecond=0)
        call = Activity(key="f:1", ts=iso(t0), kind="tool_call",
                        tool_name="Bash", tool_use_id="c1",
                        started_ts=iso(t0), summary="Bash: pytest")
        self.store.apply(self.entry, 1, self._result(activities=[call]))
        s = self.store.get("s1")
        self.assertIn("c1", s.pending_tools)

        later = t0 + timedelta(seconds=2)
        result = Activity(key="f:2", ts=iso(later), kind="tool_result",
                          tool_use_id="c1", summary="ok")
        self.store.apply(self.entry, 2, self._result(activities=[result]))
        s = self.store.get("s1")
        self.assertNotIn("c1", s.pending_tools)
        items = self.store.activities("s1")["items"]
        self.assertEqual(items[-1]["duration_ms"], 2000)

    def test_current_action_tracks_last_call(self):
        a1 = Activity(key="f:1", ts=iso(NOW), kind="assistant_text",
                      summary="thinking out loud")
        self.store.apply(self.entry, 1, self._result(activities=[a1]))
        a2 = Activity(key="f:2", ts=iso(NOW), kind="tool_call",
                      tool_name="Read", summary="Read: x.py")
        self.store.apply(self.entry, 2, self._result(activities=[a2]))
        self.assertEqual(self.store.get("s1").current_action.summary,
                         "Read: x.py")

    def test_activities_pagination(self):
        for i in range(10):
            act = Activity(key=f"f:{i}", ts=iso(NOW), kind="assistant_text",
                           summary=f"line {i}")
            self.store.apply(self.entry, i + 1,
                             self._result(activities=[act]))
        # newest window of 4, cursor points at the oldest of the window
        page = self.store.activities("s1", limit=4)
        self.assertEqual([a["summary"] for a in page["items"]],
                         ["line 6", "line 7", "line 8", "line 9"])
        self.assertEqual(page["next"], "f:6")
        # "load older": the 4 items preceding f:6
        older = self.store.activities("s1", before_key="f:6", limit=4)
        self.assertEqual([a["summary"] for a in older["items"]],
                         ["line 2", "line 3", "line 4", "line 5"])
        self.assertEqual(older["next"], "f:2")
        # one more page, ring exhausted
        oldest = self.store.activities("s1", before_key="f:2", limit=4)
        self.assertEqual([a["summary"] for a in oldest["items"]],
                         ["line 0", "line 1"])
        self.assertIsNone(oldest["next"])

    def test_drop_session(self):
        act = Activity(key="f:1", ts=iso(NOW), kind="user_prompt",
                       summary="hello")
        self.store.apply(self.entry, 1, self._result(activities=[act]))
        self.store.drop_session("s1")
        self.assertIsNone(self.store.get("s1"))
        self.assertEqual(self.store.activities("s1")["items"], [])

    def test_ts_to_epoch(self):
        self.assertEqual(ts_to_epoch(None), None)
        self.assertEqual(ts_to_epoch("not a date"), None)
        t = ts_to_epoch("2026-09-14T12:00:00Z")
        self.assertAlmostEqual(t, 1789387200, delta=1)


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(source_root=Path("."), idle_seconds=180,
                          stall_tool_seconds=300,
                          active_window_minutes=30)

    def _session(self, last_iso=None, pending_start=None, mtime_ns=0):
        s = Session(session_id="s", project_dir="p")
        if last_iso:
            s.last_activity_at = last_iso
        if pending_start:
            s.pending_tools["c1"] = ToolCall(
                tool_use_id="c1", name="Bash", brief="Bash: x",
                started_ts=pending_start)
        s.last_mtime_ns = mtime_ns
        return s

    def test_active(self):
        s = self._session(last_iso=iso(NOW - timedelta(seconds=10)))
        self.assertEqual(classify(s, self.cfg, NOW.timestamp()), "active")

    def test_idle(self):
        s = self._session(last_iso=iso(NOW - timedelta(minutes=5)))
        self.assertEqual(classify(s, self.cfg, NOW.timestamp()), "idle")

    def test_archived(self):
        s = self._session(last_iso=iso(NOW - timedelta(hours=3)))
        self.assertEqual(classify(s, self.cfg, NOW.timestamp()),
                         "archived")

    def test_stalled_requires_both_conditions(self):
        old = iso(NOW - timedelta(minutes=10))
        s = self._session(last_iso=old, pending_start=old,
                          mtime_ns=int((NOW - timedelta(minutes=10))
                                       .timestamp() * 1e9))
        self.assertEqual(classify(s, self.cfg, NOW.timestamp()),
                         "stalled")

    def test_pending_but_file_moving_is_not_stalled(self):
        old = iso(NOW - timedelta(minutes=10))
        s = self._session(last_iso=old, pending_start=old,
                          mtime_ns=int((NOW - timedelta(seconds=5))
                                       .timestamp() * 1e9))
        self.assertNotEqual(classify(s, self.cfg, NOW.timestamp()),
                            "stalled")

    def test_ancient_pending_tool_is_archived_not_stalled(self):
        # a session interrupted mid-tool-call days ago is not "stalled"
        # forever - it left the recent window, so it archives.
        ancient = iso(NOW - timedelta(hours=6))
        s = self._session(last_iso=ancient, pending_start=ancient,
                          mtime_ns=int((NOW - timedelta(hours=6))
                                       .timestamp() * 1e9))
        self.assertEqual(classify(s, self.cfg, NOW.timestamp()),
                         "archived")

    def test_no_timestamps_archived(self):
        s = self._session()
        self.assertEqual(classify(s, self.cfg, NOW.timestamp()),
                         "archived")


if __name__ == "__main__":
    unittest.main()
