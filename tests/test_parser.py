"""Unit tests for fishbowl.parser - hand-written line samples."""
import unittest

from fishbowl.parser import (
    LineContext, parse_line, brief_tool_input, summarize_result,
    KIND_USER_PROMPT, KIND_ASSISTANT_TEXT, KIND_THINKING, KIND_TOOL_CALL,
    KIND_TOOL_RESULT, KIND_WORKFLOW, KIND_QUEUE, KIND_PARSE_ERROR,
)

CTX = LineContext(file_id="proj/sess.jsonl", line_no=1,
                  session_id="sess", preview_chars=60)


def parse(obj, **kw):
    ctx = LineContext(file_id="proj/sess.jsonl", line_no=1, session_id="sess",
                      preview_chars=60, **kw)
    return parse_line(obj, ctx)


class AssistantLineTests(unittest.TestCase):
    def test_content_blocks(self):
        obj = {
            "type": "assistant", "timestamp": "2026-09-14T10:00:00Z",
            "isSidechain": False,
            "message": {
                "model": "claude-sonnet-5",
                "usage": {"input_tokens": 10, "cache_read_input_tokens": 20,
                          "cache_creation_input_tokens": 5,
                          "output_tokens": 30,
                          "output_tokens_details": {"thinking_tokens": 7}},
                "content": [
                    {"type": "thinking", "thinking": "Let me look at the file."},
                    {"type": "text", "text": "I will read the config now."},
                    {"type": "tool_use", "id": "call_1", "name": "Read",
                     "input": {"file_path": "src/a.py"}},
                ],
            },
        }
        r = parse(obj)
        self.assertEqual([a.kind for a in r.activities],
                         [KIND_THINKING, KIND_ASSISTANT_TEXT, KIND_TOOL_CALL])
        call = r.activities[2]
        self.assertEqual(call.tool_name, "Read")
        self.assertEqual(call.tool_use_id, "call_1")
        self.assertEqual(call.started_ts, "2026-09-14T10:00:00Z")
        self.assertIn("src/a.py", call.summary)
        self.assertFalse(call.sidechain)
        self.assertEqual(r.usage["input_tokens"], 10)
        self.assertEqual(r.model, "claude-sonnet-5")

    def test_sidechain_flag(self):
        obj = {"type": "assistant", "timestamp": "t", "isSidechain": True,
               "message": {"content": [{"type": "text", "text": "hi"}]}}
        r = parse(obj)
        self.assertTrue(r.activities[0].sidechain)
        obj2 = {"type": "assistant", "timestamp": "t",
                "message": {"content": [{"type": "text", "text": "hi"}]}}
        r2 = parse(obj2, role="subagent")
        self.assertTrue(r2.activities[0].sidechain)
        r3 = parse(obj2)
        self.assertFalse(r3.activities[0].sidechain)

    def test_unknown_type_counted(self):
        r = parse({"type": "document", "text": "x"})
        self.assertEqual(r.activities, [])
        self.assertEqual(r.counted_as, "document")
        r2 = parse({"type": "brand-new-thing"})
        self.assertEqual(r2.counted_as, "untyped_brand-new-thing")


class UserLineTests(unittest.TestCase):
    def test_string_prompt(self):
        obj = {"type": "user", "timestamp": "2026-09-14T09:59:00Z",
               "message": {"content": "fix the login bug"}}
        r = parse(obj)
        self.assertEqual(r.activities[0].kind, KIND_USER_PROMPT)
        self.assertEqual(r.activities[0].summary, "fix the login bug")

    def test_tool_result_with_detail(self):
        obj = {
            "type": "user", "timestamp": "2026-09-14T10:00:05Z",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": "call_1",
                 "content": "ok"}]},
            "toolUseResult": {"stdout": "3 files changed\n", "stderr": ""},
        }
        r = parse(obj)
        self.assertEqual(len(r.activities), 1)
        a = r.activities[0]
        self.assertEqual(a.kind, KIND_TOOL_RESULT)
        self.assertEqual(a.tool_use_id, "call_1")
        self.assertEqual(a.summary, "3 files changed")
        self.assertFalse(a.is_error)

    def test_tool_result_error(self):
        obj = {
            "type": "user", "timestamp": "t",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": "call_2",
                 "is_error": True, "content": "boom"}]},
        }
        r = parse(obj)
        self.assertTrue(r.activities[0].is_error)

    def test_tool_denial(self):
        obj = {
            "type": "user", "timestamp": "t", "toolDenialKind": "permission",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": "c", "content": ""}]},
        }
        r = parse(obj)
        self.assertTrue(r.activities[0].is_error)
        self.assertIn("permission", r.activities[0].summary)

    def test_text_block_without_result_is_prompt(self):
        obj = {"type": "user", "timestamp": "t",
               "message": {"content": [{"type": "text", "text": "hello"}]}}
        r = parse(obj)
        self.assertEqual(r.activities[0].kind, KIND_USER_PROMPT)


class MetaLineTests(unittest.TestCase):
    def test_ai_title(self):
        r = parse({"type": "ai-title", "aiTitle": "Fix login flow"})
        self.assertEqual(r.title, "Fix login flow")
        self.assertEqual(r.activities, [])

    def test_summary_title(self):
        r = parse({"type": "summary", "summary": "Old session"})
        self.assertEqual(r.title, "Old session")

    def test_common_fields(self):
        obj = {"type": "queue-operation", "op": "enqueue",
               "cwd": "/home/u/p", "gitBranch": "main", "version": "2.1.0"}
        r = parse(obj)
        self.assertEqual(r.cwd, "/home/u/p")
        self.assertEqual(r.git_branch, "main")
        self.assertEqual(r.version, "2.1.0")
        self.assertEqual(r.activities[0].kind, KIND_QUEUE)

    def test_workflow_journal(self):
        obj = {"type": "started", "key": "v2:abc", "agentId": "a1b2"}
        r = parse(obj, role="workflow")
        self.assertEqual(r.activities[0].kind, KIND_WORKFLOW)
        self.assertIn("a1b2", r.activities[0].summary)
        # not in workflow role -> counted as untyped
        r2 = parse(obj)
        self.assertEqual(r2.counted_as, "untyped_started")

    def test_broken_line_never_raises(self):
        r = parse_line({"type": "assistant", "message": None},
                       LineContext(file_id="f", line_no=9, session_id="s"))
        self.assertTrue(len(r.activities) >= 0)  # no exception is the test


class SummaryHelperTests(unittest.TestCase):
    def test_brief_bash_first_line(self):
        brief = brief_tool_input("Bash", {"command": "git rebase --abort\n"
                                           "cd /tmp"}, 60)
        self.assertEqual(brief, "Bash: git rebase --abort")

    def test_brief_read(self):
        self.assertEqual(brief_tool_input("Read", {"file_path": "a.py"}, 60),
                         "Read: a.py")

    def test_brief_no_input(self):
        self.assertEqual(brief_tool_input("Skill", {}, 60), "Skill")

    def test_summarize_write(self):
        s, err = summarize_result(
            {"type": "create", "filePath": "src/x.py"}, {}, 60)
        self.assertEqual(s, "wrote src/x.py")
        self.assertFalse(err)

    def test_summarize_error_string(self):
        s, err = summarize_result("Error: file not found", {}, 60)
        self.assertTrue(err)
        self.assertEqual(s, "Error: file not found")

    def test_summarize_block_content_fallback(self):
        s, err = summarize_result(
            None, {"content": [{"type": "text", "text": "plain output"}]}, 60)
        self.assertEqual(s, "plain output")
        self.assertFalse(err)


if __name__ == "__main__":
    unittest.main()
