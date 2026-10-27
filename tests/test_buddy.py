import importlib.machinery
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("buddy", str(ROOT / "buddy.pyw"))
buddy = importlib.util.module_from_spec(importlib.util.spec_from_loader("buddy", _loader))
_loader.exec_module(buddy)


class CharFont:
    """Stands in for a Tk font: every character is 1px wide."""

    def measure(self, text):
        return len(text)


class WrappedLines(unittest.TestCase):
    def test_short_text_is_one_line(self):
        self.assertEqual(buddy.count_wrapped_lines("hello there", CharFont(), 40), 1)

    def test_words_wrap_at_width(self):
        # "aaaa bbbb" is 9 wide, so a 6-wide line holds one word.
        self.assertEqual(buddy.count_wrapped_lines("aaaa bbbb cccc", CharFont(), 6), 3)

    def test_newlines_and_blank_lines_count(self):
        self.assertEqual(buddy.count_wrapped_lines("one\n\nthree", CharFont(), 40), 3)

    def test_word_wider_than_line_breaks(self):
        self.assertEqual(buddy.count_wrapped_lines("x" * 25, CharFont(), 10), 3)


class ClaudeEnv(unittest.TestCase):
    def test_strips_api_key_and_parent_session(self):
        env = {"PATH": "p", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_BASE_URL": "u",
               "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "s", "CLAUDE_CONFIG_DIR": "d"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(buddy.claude_env(), {"PATH": "p", "CLAUDE_CONFIG_DIR": "d"})


class ParseStreamLine(unittest.TestCase):
    def text_delta(self, s):
        return json.dumps({"type": "stream_event",
                           "event": {"type": "content_block_delta",
                                     "delta": {"type": "text_delta", "text": s}}})

    def test_text_delta_yields_text(self):
        self.assertEqual(buddy.parse_stream_line(self.text_delta("hi ")), [("text", "hi ")])

    def test_tool_start_yields_tool_name(self):
        line = json.dumps({"type": "stream_event",
                           "event": {"type": "content_block_start",
                                     "content_block": {"type": "tool_use", "name": "Bash"}}})
        self.assertEqual(buddy.parse_stream_line(line), [("tool", "Bash")])

    def test_result_success(self):
        line = json.dumps({"type": "result", "is_error": False, "result": "done"})
        self.assertEqual(buddy.parse_stream_line(line), [("result", True, "done")])

    def test_result_error(self):
        line = json.dumps({"type": "result", "is_error": True, "result": "boom"})
        self.assertEqual(buddy.parse_stream_line(line), [("result", False, "boom")])

    def test_noise_and_blank_and_bad_json_are_ignored(self):
        self.assertEqual(buddy.parse_stream_line(""), [])
        self.assertEqual(buddy.parse_stream_line("not json"), [])
        self.assertEqual(buddy.parse_stream_line(json.dumps({"type": "system"})), [])
        # A thinking delta is not shown in the bubble.
        thinking = json.dumps({"type": "stream_event",
                               "event": {"type": "content_block_delta",
                                         "delta": {"type": "thinking_delta", "thinking": "hm"}}})
        self.assertEqual(buddy.parse_stream_line(thinking), [])


class StreamClaude(unittest.TestCase):
    """stream_claude against a stand-in executable that prints stream-json lines."""

    def run_script(self, script, mode="ask"):
        events, started = [], []
        conf = {"label": "T", "args": ["-c", script], "cwd": os.getcwd(),
                "timeout": 60, "verb": "T"}
        with mock.patch.dict(buddy.MODES, {mode: conf}):
            buddy.stream_claude(sys.executable, mode, "a prompt", started.append, events.append)
        self.assertEqual(len(started), 1)
        return events

    def test_streams_deltas_then_result(self):
        script = (
            "import json,sys; sys.stdin.read();"
            "d=lambda s: print(json.dumps({'type':'stream_event','event':"
            "{'type':'content_block_delta','delta':{'type':'text_delta','text':s}}}));"
            "d('Hel'); d('lo');"
            "print(json.dumps({'type':'result','is_error':False,'result':'Hello'}))"
        )
        events = self.run_script(script)
        self.assertEqual(events,
                         [("text", "Hel"), ("text", "lo"), ("result", True, "Hello")])

    def test_crash_without_result_reports_stderr(self):
        script = "import sys; sys.stdin.read(); sys.stderr.write('not logged in'); sys.exit(1)"
        events = self.run_script(script)
        self.assertEqual(events, [("result", False, "not logged in")])


class ModeWiring(unittest.TestCase):
    def test_ask_is_tool_free_and_browserless(self):
        args = buddy.MODES["ask"]["args"]
        self.assertIn("--safe-mode", args)
        self.assertIn("--tools", args)
        self.assertNotIn("--chrome", args)
        self.assertNotIn("--permission-mode", args)

    def test_do_has_chrome_and_full_permissions(self):
        args = buddy.MODES["do"]["args"]
        self.assertIn("--chrome", args)
        self.assertEqual(args[args.index("--permission-mode") + 1], "bypassPermissions")
        self.assertNotIn("--safe-mode", args)


class RoundRect(unittest.TestCase):
    def test_corners_stay_inside_the_box(self):
        points = buddy.round_rect(0, 0, 100, 50, 10)
        xs, ys = points[0::2], points[1::2]
        self.assertEqual((min(xs), max(xs), min(ys), max(ys)), (0, 100, 0, 50))


if __name__ == "__main__":
    unittest.main()
