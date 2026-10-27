import importlib.machinery
import importlib.util
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


class RunClaude(unittest.TestCase):
    """run_claude against a stand-in executable, so no real Claude call is made."""

    def run_with(self, script):
        started = []
        with mock.patch.object(buddy, "CLAUDE_ARGS", ["-c", script]):
            result = buddy.run_claude(sys.executable, "hi there", started.append)
        self.assertEqual(len(started), 1)
        return result

    def test_reply_comes_from_stdout_with_prompt_on_stdin(self):
        ok, text = self.run_with("import sys; print(sys.stdin.read().upper())")
        self.assertEqual((ok, text), (True, "HI THERE"))

    def test_failure_reports_stderr(self):
        ok, text = self.run_with("import sys; sys.stderr.write('not logged in'); sys.exit(1)")
        self.assertEqual((ok, text), (False, "not logged in"))

    def test_empty_reply_is_an_error(self):
        ok, text = self.run_with("pass")
        self.assertFalse(ok)
        self.assertIn("exited with code 0", text)


class RoundRect(unittest.TestCase):
    def test_corners_stay_inside_the_box(self):
        points = buddy.round_rect(0, 0, 100, 50, 10)
        xs, ys = points[0::2], points[1::2]
        self.assertEqual((min(xs), max(xs), min(ys), max(ys)), (0, 100, 0, 50))


if __name__ == "__main__":
    unittest.main()
