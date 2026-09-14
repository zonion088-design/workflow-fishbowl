"""API end-to-end tests: real server on an ephemeral loopback port."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fishbowl.app import App
from fishbowl.config import Config, load_prices
from fishbowl.fixtures_gen import make_fixture_tree
from fishbowl.server import make_server

REPO = Path(__file__).resolve().parent.parent


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        make_fixture_tree(cls.tmp, now=datetime.now(timezone.utc))
        cfg = Config(source_root=cls.tmp, cache_path=None,
                     prices=load_prices(REPO / "fishbowl" / "prices.json"))
        cls.app = App(cfg)
        cls.app.scan_once()
        cls.server = make_server(cls.app)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, kwargs={"poll_interval": 0.2},
            daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, expect=200):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                self.assertEqual(r.status, expect)
                self.assertIn("default-src 'self'",
                              r.headers.get("Content-Security-Policy", ""))
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, expect)
            return json.loads(e.read().decode("utf-8"))

    def test_health(self):
        d = self.get("/api/health")
        self.assertEqual(d["mode"], "live")
        self.assertFalse(d["indexing"])
        # 6 main transcripts + 2 subagents + 1 workflow journal
        self.assertEqual(d["files_watched"], 9)

    def test_sessions_shape(self):
        d = self.get("/api/sessions")
        self.assertEqual(len(d["sessions"]), 5)
        by_status = {s["status"] for s in d["sessions"]}
        self.assertIn("stalled", by_status)
        for s in d["sessions"]:
            self.assertIn("title", s)
            self.assertIn("current_action", s)
            self.assertIn("usage", s)
            self.assertIn("cost_usd", s)

    def test_session_detail(self):
        sessions = self.get("/api/sessions")["sessions"]
        sid = sessions[0]["session_id"]
        d = self.get(f"/api/sessions/{sid}")
        self.assertEqual(d["session"]["session_id"], sid)
        self.assertIsInstance(d["activities"], list)

    def test_activities_pagination(self):
        sessions = self.get("/api/sessions")["sessions"]
        sid = sessions[0]["session_id"]
        d = self.get(f"/api/sessions/{sid}/activities?limit=2")
        self.assertLessEqual(len(d["items"]), 2)
        if d["next"]:
            older = self.get(
                f"/api/sessions/{sid}/activities?limit=2&before={d['next']}")
            self.assertLessEqual(len(older["items"]), 2)

    def test_projects(self):
        d = self.get("/api/projects")
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["session_count"], 5)

    def test_stats(self):
        d = self.get("/api/stats")
        self.assertEqual(d["session_count"], 5)
        self.assertGreater(len(d["by_model"]), 0)
        self.assertIn("sessions_by_status", d)

    def test_unknown_session_404(self):
        self.get("/api/sessions/nope", expect=404)

    def test_unknown_route_404(self):
        self.get("/api/whatever", expect=404)

    def test_post_rejected(self):
        url = f"http://127.0.0.1:{self.port}/api/sessions"
        req = urllib.request.Request(
            url, data=b"{}", method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                self.fail("POST should not succeed")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 405)

    def test_static_index(self):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/", timeout=5) as r:
            body = r.read().decode("utf-8")
            self.assertIn("fishbowl", body)

    def test_static_traversal_blocked(self):
        self.get("/../LICENSE", expect=404)


if __name__ == "__main__":
    unittest.main()
