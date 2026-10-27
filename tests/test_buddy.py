import importlib.machinery
import importlib.util
import json
import os
import queue
import sys
import time
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

    def test_timeout_covers_silent_stdout(self):
        self.check_timeout("import sys,time; sys.stdin.read(); time.sleep(10)")

    def test_timeout_covers_blocked_stdin(self):
        self.check_timeout("import time; time.sleep(10)", prompt="x" * 1_000_000)

    def test_timeout_covers_continuous_output(self):
        self.check_timeout("import time\nwhile True:\n print('{}', flush=True)\n time.sleep(.01)")

    def check_timeout(self, script, prompt="hi"):
        events, started = [], []
        conf = {"args": ["-c", script], "cwd": os.getcwd(), "timeout": .2}
        before = time.monotonic()
        with mock.patch.dict(buddy.MODES, {"ask": conf}):
            buddy.stream_claude(sys.executable, "ask", prompt, started.append, events.append)
        self.assertLess(time.monotonic() - before, 3)
        self.assertIsNotNone(started[0].poll())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][:2], ("result", False))
        self.assertIn("so I stopped it", events[0][2])
        self.assertTrue(all(pipe.closed for pipe in
                            (started[0].stdin, started[0].stdout, started[0].stderr)))


class PetAnimation(unittest.TestCase):
    def test_idle_contains_a_blink_and_greeting(self):
        poses = [buddy.pet_pose(i) for i in range(240)]
        self.assertTrue(any(p["blink"] for p in poses))
        self.assertTrue(any(p["wave"] for p in poses))
        self.assertGreater(len({p["bob"] for p in poses}), 1)

    def test_activity_poses_have_distinct_motion(self):
        self.assertTrue(buddy.pet_pose(10, "happy")["wave"])
        self.assertLess(buddy.pet_pose(10, "happy")["hop"], 0)
        self.assertNotEqual(buddy.pet_pose(10, "working")["arm"], 0)
        self.assertEqual(buddy.pet_pose(10, "thinking")["look"], 2)

    def test_thinking_dots_clear_after_result_and_cancel(self):
        pet = buddy.Buddy.__new__(buddy.Buddy)
        pet.canvas, pet.root = mock.Mock(), mock.Mock()
        pet.draw_pet = mock.Mock()
        pet.tick_count, pet.press = 9, None
        pet.reaction_until, pet.activity = 0, "thinking"
        pet.busy = True
        pet.tick()
        pet.canvas.itemconfigure.assert_any_call("dot0", state="normal")
        pet.events = queue.Queue()
        pet.request_id, pet.last_mode, pet.pending_prompt = 1, "ask", "hello"
        pet.stream_buf = ""
        pet.show_reply = mock.Mock()
        for finish in ("success", "error", "cancel"):
            pet.busy = True
            if finish != "cancel":
                pet.events.put((pet.request_id, ("result", finish == "success", "done")))
                with mock.patch.object(buddy, "append_history"):
                    pet.poll_events()
            else:
                pet.proc = mock.Mock()
                pet.proc.poll.return_value = None
                proc = pet.proc
                pet.cancel()
                proc.kill.assert_called_once()
            self.assertFalse(pet.busy)
            pet.canvas.reset_mock()
            pet.tick()
            for i in range(3):
                pet.canvas.itemconfigure.assert_any_call(f"dot{i}", state="hidden")


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


class SessionLaunch(unittest.TestCase):
    def test_uses_windows_terminal_when_present(self):
        self.assertEqual(buddy.session_launch_command("claude.exe", True, r"C:\gh"),
                         ["wt", "-d", r"C:\gh", "claude.exe"])

    def test_falls_back_to_console(self):
        cmd = buddy.session_launch_command("claude.exe", False, r"C:\gh")
        self.assertEqual(cmd[:3], ["cmd", "/c", "start"])
        self.assertEqual(cmd[-3:], ["cmd", "/k", "claude.exe"])

    def test_defaults_exe_name_when_missing(self):
        self.assertEqual(buddy.session_launch_command(None, True, "C:\\")[-1], "claude")


class HistoryMemory(unittest.TestCase):
    def test_build_prompt_passthrough_when_empty(self):
        self.assertEqual(buddy.build_prompt([], "hello"), "hello")

    def test_build_prompt_includes_prior_exchanges(self):
        history = [{"prompt": "what is my name", "reply": "Mohammed"}]
        out = buddy.build_prompt(history, "and my school?")
        self.assertIn("Mohammed", out)
        self.assertTrue(out.rstrip().endswith("and my school?"))

    def test_append_and_load_roundtrip_truncates_long_replies(self):
        import pathlib
        import tempfile
        d = pathlib.Path(tempfile.mkdtemp())
        with mock.patch.object(buddy, "APP_DIR", d), \
                mock.patch.object(buddy, "HISTORY_FILE", d / "history.jsonl"):
            buddy.append_history("ask", "q1", "r1")
            buddy.append_history("do", "q2", "x" * 900)
            rows = buddy.load_recent_history(5)
        self.assertEqual([r["prompt"] for r in rows], ["q1", "q2"])
        self.assertLessEqual(len(rows[1]["reply"]), buddy.HISTORY_REPLY_CHARS)

    def test_compose_prompt_adds_learned_facts(self):
        out = buddy.compose_prompt("- likes teal", [], "hi")
        self.assertIn("likes teal", out)
        self.assertTrue(out.rstrip().endswith("hi"))

    def test_compose_prompt_without_learned_is_just_history(self):
        self.assertEqual(buddy.compose_prompt("", [], "hi"), buddy.build_prompt([], "hi"))

    def test_load_learned_missing_file_is_empty(self):
        import pathlib
        with mock.patch.object(buddy, "LEARNED_FILE", pathlib.Path("does-not-exist.md")):
            self.assertEqual(buddy.load_learned(), "")


class RoundRect(unittest.TestCase):
    def test_corners_stay_inside_the_box(self):
        points = buddy.round_rect(0, 0, 100, 50, 10)
        xs, ys = points[0::2], points[1::2]
        self.assertEqual((min(xs), max(xs), min(ys), max(ys)), (0, 100, 0, 50))


if __name__ == "__main__":
    unittest.main()
