"""Codex rollout adapter and parser tests use synthetic data only."""
import json
import tempfile
import unittest
from pathlib import Path

from fishbowl.codex import CodexAdapter, parse_codex_line
from fishbowl.parser import LineContext


class CodexTests(unittest.TestCase):
    def ctx(self):
        return LineContext("codex/test.jsonl", 1, "session")

    def test_user_message(self):
        result = parse_codex_line({
            "timestamp": "2026-01-01T00:00:00Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "hello"},
        }, self.ctx())
        self.assertEqual(result.activities[0].kind, "user_prompt")

    def test_tool_call(self):
        result = parse_codex_line({
            "type": "response_item",
            "payload": {"type": "function_call", "name": "shell",
                        "call_id": "c1", "arguments": "{\"cmd\":\"pwd\"}"},
        }, self.ctx())
        self.assertEqual(result.activities[0].tool_use_id, "c1")

    def test_discovery_uses_session_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "2026" / "rollout.jsonl"
            path.parent.mkdir()
            path.write_text(json.dumps({
                "type": "session_meta",
                "payload": {"session_id": "abc", "cwd": "/work/demo"},
            }) + "\n", encoding="utf-8")
            entries, metas = CodexAdapter(root).discover()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].session_id, "abc")
            self.assertEqual(entries[0].project_dir, "demo")
            self.assertEqual(entries[0].format, "codex")
            self.assertEqual(metas, [])


if __name__ == "__main__":
    unittest.main()
