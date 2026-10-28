"""Claude Buddy: a floating desktop assistant that puts Claude one click away.

Run with `pythonw buddy.pyw`. Two modes share one pencil:

- **Ask** (default): a fast, chat-only `claude` call that cannot touch files,
  run commands, or reach your accounts. For quick questions.
- **Do it**: full `claude` with your tools, connectors, and dotgithub context,
  so it can find a doc, run a task, or start work. It can change things on your
  machine, so it is a deliberate second mode, never the default.

Replies stream into the speech bubble as they arrive. The mic starts Windows
voice typing (Win+H). Right-click the mascot for the menu. Claude is reached
through the `claude` CLI, so it uses your login, not an API key.
"""

import ctypes
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
from ctypes import wintypes
from pathlib import Path

from pip_art import PetRenderer, pet_pose

# State lives outside AppData: launched from an MSIX app (such as the Claude
# desktop app), an AppData write would land in that app's private copy and be
# lost to a Pip started at sign-in.
APP_DIR = Path.home() / ".local" / "state" / "claude-buddy"
STATE_FILE = APP_DIR / "state.json"
LOG_FILE = APP_DIR / "buddy.log"
# A local rolling log of recent exchanges, so Pip keeps continuity and does not
# re-ask what it just learned. His own machine only; never synced anywhere.
HISTORY_FILE = APP_DIR / "history.jsonl"
HISTORY_KEEP = 6
HISTORY_REPLY_CHARS = 500
# Durable facts Pip has learned about him, beyond the rolling history. Pip's own
# copy, always loaded into context so it never re-asks what it has been told.
LEARNED_FILE = APP_DIR / "learned.md"
# Where a screen capture is written for Do-it to read.
SCREEN_FILE = APP_DIR / "screen.png"

GITHUB_DIR = Path.home() / "Github"  # dotgithub checkout: his CLAUDE.md and brain, for Do-it

# Flags shared by both modes: stream the reply as it is generated.
STREAM_ARGS = ["-p", "--output-format", "stream-json", "--include-partial-messages",
               "--verbose", "--no-session-persistence"]

ASK_SYSTEM = ("You are answering inside a small desktop speech bubble. Keep replies short "
              "and write plain text, no Markdown. You have no tools; just answer. Recent "
              "exchanges may be included for continuity, which carry across questions, so use "
              "them and don't say you can't remember.")
DO_SYSTEM = ("You are Mohammed's personal intelligence, answering from a small speech bubble with "
             "full tools, his connectors, and his dotgithub second brain. You run inside his "
             "dotgithub checkout: read knowledge/me/profile.md and knowledge/me/facts.md for who "
             "he is, his projects, and his preferences, and never re-ask what they already answer. "
             "Do what he asks, then "
             "report the result in a few plain-text sentences, no Markdown. His documents live "
             "in Google Drive; use the Google Drive connector to find and read them. For anything "
             "on a website, use Claude in Chrome, his real signed-in browser: load the "
             "mcp__claude-in-chrome__* tools with ToolSearch, then act in his existing sessions. "
             "Never try to hide the automation from a site, bypass a sign-in, or defeat a bot "
             "check. Do not take irreversible or outward actions he did not ask for: no deleting, "
             "no force-push, no sending messages or posting, no spending. Recent exchanges may "
             "be included for continuity, which carry across questions, so use them and don't "
             "say you can't remember. When he tells you to remember something durable about "
             "him, append one line to his personal memory file at " + LEARNED_FILE.as_posix() +
             " (create it if missing) as `- YYYY-MM-DD: <fact>`, and append the same to "
             "knowledge/me/facts.md as `- YYYY-MM-DD: <fact> (source: Mohammed, via Claude "
             "Buddy)`; do not commit or push either file. When a task is ambiguous, do the "
             "safest useful version and say what you did.")

MODES = {
    # Ask: no tools, no context load, safe by construction. Fast.
    "ask": {
        "label": "Ask",
        "args": STREAM_ARGS + ["--safe-mode", "--tools", "", "--append-system-prompt", ASK_SYSTEM],
        "cwd": str(Path.home()),
        "timeout": 300,
        "verb": "Claude",
    },
    # Do it: full tools and connectors, dotgithub context, and Claude in Chrome
    # (his real signed-in browser) for website tasks. Runs unattended.
    "do": {
        "label": "Do it",
        "args": STREAM_ARGS + ["--permission-mode", "bypassPermissions", "--chrome",
                               "--add-dir", str(GITHUB_DIR), "--append-system-prompt", DO_SYSTEM],
        "cwd": str(GITHUB_DIR) if GITHUB_DIR.exists() else str(Path.home()),
        "timeout": 1800,
        "verb": "Did it",
    },
}

KEY = "#ff00ff"  # transparent color key; never used in the drawing
CLAY = "#d97757"  # Claude terracotta
CLAY_DARK = "#b85c3c"
CLAY_SHEEN = "#e79a80"
EYE = "#faf1ec"  # knockout eyes, like the Claude Code mascot
INK = "#2b2622"
PAPER = "#ffffff"
PAPER_EDGE = "#e4d8d0"
HOVER = "#f6ece6"
MUTED = "#8a7a70"
ERROR = "#b3261e"
SEL_ON = CLAY
SEL_OFF = "#efe6e0"

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetAncestor.restype = ctypes.c_void_p
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.MonitorFromPoint.restype = ctypes.c_void_p
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]


def log(message):
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def already_running():
    global _instance_mutex
    _instance_mutex = kernel32.CreateMutexW(None, False, "Local\\ClaudeBuddySingleInstance")
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


def work_area_at(x, y):
    """Work area (screen minus taskbar) of the monitor nearest to (x, y)."""
    monitor = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(monitor, ctypes.byref(info))
    r = info.rcWork
    return r.left, r.top, r.right, r.bottom


def keep_on_top(win):
    """Re-assert topmost without stealing focus, so apps like Zoom can't bury us."""
    hwnd = user32.GetAncestor(win.winfo_id(), 2)  # GA_ROOT
    flags = 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
    user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), 0, 0, 0, 0, flags)


def press_win_h():
    """Open Windows voice typing in whatever control has focus."""
    vk_lwin, vk_h, keyup = 0x5B, 0x48, 0x0002
    user32.keybd_event(vk_lwin, 0, 0, 0)
    user32.keybd_event(vk_h, 0, 0, 0)
    user32.keybd_event(vk_h, 0, keyup, 0)
    user32.keybd_event(vk_lwin, 0, keyup, 0)


def find_claude():
    exe = shutil.which("claude")
    if exe:
        return exe
    fallback = Path.home() / ".local" / "bin" / "claude.exe"
    return str(fallback) if fallback.exists() else None


def claude_env():
    # Drop variables an API key or a parent Claude session would inject, so the
    # CLI always answers on the logged-in Claude subscription.
    return {k: v for k, v in os.environ.items()
            if not k.startswith(("ANTHROPIC_", "CLAUDE")) or k == "CLAUDE_CONFIG_DIR"}


def session_launch_command(exe, has_wt, cwd):
    """How to open a new interactive Claude Code session: Windows Terminal if it
    is present, otherwise a plain console window."""
    exe = exe or "claude"
    if has_wt:
        return ["wt", "-d", cwd, exe]
    return ["cmd", "/c", "start", "Claude Code", "cmd", "/k", exe]


def load_recent_history(n=HISTORY_KEEP):
    try:
        lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def append_history(mode, prompt, reply):
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%d %H:%M"), "mode": mode,
                 "prompt": prompt, "reply": reply[:HISTORY_REPLY_CHARS]}
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        log(f"could not save history: {exc}")


def build_prompt(history, user_prompt):
    """Prepend recent exchanges so Pip keeps continuity across questions."""
    if not history:
        return user_prompt
    lines = ["[Context from earlier in this ongoing conversation with Mohammed, oldest first. "
             "Use it for continuity and do not re-ask what is already answered.]"]
    for entry in history:
        lines.append(f"Mohammed: {entry.get('prompt', '')}")
        lines.append(f"You: {entry.get('reply', '')}")
    lines.append("")
    lines.append(f"Mohammed now says: {user_prompt}")
    return "\n".join(lines)


def load_learned():
    try:
        return LEARNED_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


def compose_prompt(learned, history, user_prompt):
    """Durable facts, then recent exchanges, then the new question."""
    base = build_prompt(history, user_prompt)
    if learned.strip():
        return ("[Durable facts you already know about Mohammed — treat as known, don't re-ask:]\n"
                + learned.strip() + "\n\n" + base)
    return base


def capture_screen(path):
    """Grab all monitors to a PNG for Do-it to read. Needs Pillow; False without it."""
    try:
        from PIL import ImageGrab
    except ImportError:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(all_screens=True).save(path)
        return True
    except (OSError, ValueError) as exc:
        log(f"screen capture failed: {exc}")
        return False


def parse_stream_line(line):
    """Turn one stream-json line into events for the UI.

    Returns a list of (kind, payload): ("text", str) for a streamed chunk,
    ("tool", name) when a tool call starts, ("result", ok, text) at the end.
    Unknown or noise lines return [].
    """
    line = line.strip()
    if not line:
        return []
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        return []
    kind = obj.get("type")
    if kind == "stream_event":
        event = obj.get("event", {})
        etype = event.get("type")
        if etype == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta" and delta.get("text"):
                return [("text", delta["text"])]
        elif etype == "content_block_start":
            block = event.get("content_block", {})
            if block.get("type") == "tool_use":
                return [("tool", block.get("name") or "a tool")]
        return []
    if kind == "result":
        return [("result", not obj.get("is_error"), (obj.get("result") or "").strip())]
    return []


def stream_claude(exe, mode, prompt, on_start, emit):
    """Run `claude` for one mode and emit UI events as its reply streams in."""
    conf = MODES[mode]
    proc = subprocess.Popen(
        [exe, *conf["args"]],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        env=claude_env(), cwd=conf["cwd"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    deadline = time.monotonic() + conf["timeout"]
    on_start(proc)
    output = queue.Queue()
    stderr_chunks = []
    def read_output():
        try:
            for line in proc.stdout:
                output.put(line)
        finally:
            output.put(None)

    def write_prompt():
        try:
            proc.stdin.write(prompt)
        except OSError:
            pass
        finally:
            proc.stdin.close()

    readers = [threading.Thread(target=read_output, daemon=True),
               threading.Thread(target=lambda: stderr_chunks.append(proc.stderr.read()), daemon=True),
               threading.Thread(target=write_prompt, daemon=True)]
    for thread in readers:
        thread.start()
    result = None
    try:
        while True:
            # The deadline applies while reading stdout AND writing stdin, even
            # if Claude goes silent or never reads its prompt.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            line = output.get(timeout=remaining)
            if line is None:
                break
            for event in parse_stream_line(line):
                if event[0] == "result":
                    result = event
                else:
                    emit(event)
        proc.wait(timeout=max(0, deadline - time.monotonic()))
    except (queue.Empty, subprocess.TimeoutExpired):
        proc.kill()
        proc.wait()
        emit(("result", False, f"That took longer than {conf['timeout'] // 60} minutes, so I stopped it."))
        return
    finally:
        for thread in readers:
            thread.join(timeout=1)
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            pipe.close()
    err = "".join(c for c in stderr_chunks if c).strip()
    emit(result or ("result", False, err or f"claude exited with code {proc.returncode}"))


def count_wrapped_lines(text, font, width):
    """Approximate how many lines a word-wrapping Text widget will need."""
    space = font.measure(" ")
    total = 0
    for paragraph in text.split("\n"):
        lines, line_w = 1, 0
        for word in paragraph.split(" "):
            w = font.measure(word)
            if line_w and line_w + space + w > width:
                lines += 1
                line_w = w
            else:
                line_w += (space if line_w else 0) + w
            while line_w > width:  # a word wider than the line breaks mid-word
                lines += 1
                line_w -= width
        total += lines
    return total


def round_rect(x1, y1, x2, y2, r):
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


class Buddy:
    def __init__(self):
        self.root = tk.Tk()
        self.scale = self.root.winfo_fpixels("1i") / 96
        self.root.report_callback_exception = self.report_error

        self.claude = find_claude()
        self.events = queue.Queue()
        self.proc = None
        self.busy = False
        self.mode = "ask"
        self.request_id = 0
        self.started = 0.0
        self.stream_buf = ""
        self.pending_prompt = ""
        self.attach_screen = None
        self.last_reply = ""
        self.last_mode = "ask"
        self.bubble_state = None
        self.press = None
        self.tick_count = 0
        self.animation_started = time.monotonic()
        self.activity = "idle"
        self.reaction_until = 0.0
        self.reaction = "happy"

        families = set(tkfont.families(self.root))
        icon_family = "Segoe Fluent Icons" if "Segoe Fluent Icons" in families else "Segoe MDL2 Assets"
        self.font = tkfont.Font(self.root, family="Segoe UI", size=10)
        self.small = tkfont.Font(self.root, family="Segoe UI", size=8)
        self.small_bold = tkfont.Font(self.root, family="Segoe UI", size=8, weight="bold")
        self.icons = tkfont.Font(self.root, family=icon_family, size=11)

        self.build_mascot()
        self.build_input()
        self.build_bubble()
        self.build_menu()
        self.restore_position()

        self.root.after(16, self.tick)
        self.root.after(80, self.poll_events)
        self.root.after(1500, self.reassert_topmost)

    def px(self, value):
        return int(round(value * self.scale))

    def xy(self, *coords):
        return [c * self.scale for c in coords]

    # ---- mascot -----------------------------------------------------------

    def build_mascot(self):
        root = self.root
        root.title("Claude Buddy")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", KEY)
        root.configure(bg=KEY)
        self.width, self.height = self.px(176), self.px(164)
        c = self.canvas = tk.Canvas(root, width=self.width, height=self.height,
                                    bg=KEY, highlightthickness=0, bd=0)
        c.pack()

        self.pet_renderer = PetRenderer(c, self.scale)
        self.draw_pet("idle")
        # Thinking dots, hidden until busy.
        for i in range(3):
            bx = self.px(47 + i * 10)
            c.create_rectangle(bx, self.px(6), bx + self.px(4), self.px(10),
                               fill=CLAY_DARK, outline="", state="hidden", tags=(f"dot{i}",))

        self.add_button("pencil", 142, 53, "")
        self.add_button("mic", 142, 89, "")

        c.tag_bind("hit", "<Enter>", lambda e: c.configure(cursor="fleur"))
        c.tag_bind("hit", "<Leave>", lambda e: c.configure(cursor=""))
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Button-3>", self.show_menu)
        root.bind("<Escape>", lambda e: self.close_bubble())

    def draw_pet(self, activity, seconds=None):
        if seconds is None:
            seconds = time.monotonic() - self.animation_started
        self.pet_renderer.draw(seconds, activity)

    def add_button(self, name, x, y, glyph):
        c = self.canvas
        tag = f"btn_{name}"
        circle = c.create_oval(*self.xy(x, y, x + 28, y + 28), fill=PAPER, outline=CLAY_DARK,
                               width=max(1, self.px(1.5)), tags=(tag, "button"))
        c.create_text(*self.xy(x + 14, y + 14), text=glyph, font=self.icons, fill=CLAY_DARK,
                      tags=(tag, "button"))
        c.tag_bind(tag, "<Enter>", lambda e: (c.itemconfigure(circle, fill=HOVER),
                                              c.configure(cursor="hand2")))
        c.tag_bind(tag, "<Leave>", lambda e: (c.itemconfigure(circle, fill=PAPER),
                                              c.configure(cursor="")))

    def target_at(self, event):
        tags = self.canvas.gettags("current")
        for name in ("pencil", "mic"):
            if f"btn_{name}" in tags:
                return name
        return "body"

    def on_press(self, event):
        self.press = {
            "target": self.target_at(event),
            "dx": event.x_root - self.root.winfo_x(),
            "dy": event.y_root - self.root.winfo_y(),
            "x": event.x_root, "y": event.y_root, "dragged": False,
        }

    def on_drag(self, event):
        p = self.press
        if not p or p["target"] != "body":
            return
        if not p["dragged"] and abs(event.x_root - p["x"]) + abs(event.y_root - p["y"]) < self.px(4):
            return
        p["dragged"] = True
        self.root.geometry(f"+{event.x_root - p['dx']}+{event.y_root - p['dy']}")
        self.place_popups()

    def on_release(self, event):
        p, self.press = self.press, None
        if not p:
            return
        if p["dragged"]:
            self.save_position()
        elif p["target"] == "mic":
            self.start_dictation()
        else:
            self.toggle_input()

    def tick(self):
        self.tick_count += 1
        c = self.canvas
        activity = "idle"
        if self.press and self.press["dragged"]:
            activity = "dragging"
        elif self.busy:
            activity = self.activity
        elif time.monotonic() < self.reaction_until:
            activity = self.reaction
        self.draw_pet(activity)
        # Always reset all three: a result/cancel can arrive at any dot phase.
        shown = int((time.monotonic() - self.animation_started) / .3) % 4 if self.busy else 0
        for i in range(3):
            c.itemconfigure(f"dot{i}", state="normal" if i < shown else "hidden")
        self.root.after(16, self.tick)

    # ---- position ---------------------------------------------------------

    def restore_position(self):
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            x, y = int(state["x"]), int(state["y"])
        except (OSError, ValueError, KeyError, TypeError):
            x, y = self.default_position()
        left, top, right, bottom = work_area_at(x + self.width // 2, y + self.height // 2)
        x = min(max(x, left), right - self.width)
        y = min(max(y, top), bottom - self.height)
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def default_position(self):
        left, top, right, bottom = work_area_at(0, 0)
        return right - self.width - self.px(24), bottom - self.height - self.px(24)

    def save_position(self):
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps({"x": self.root.winfo_x(), "y": self.root.winfo_y()}),
                                  encoding="utf-8")
        except OSError as exc:
            log(f"could not save position: {exc}")

    def reset_position(self):
        x, y = self.default_position()
        self.root.geometry(f"+{x}+{y}")
        self.place_popups()
        self.save_position()

    def popup_origin(self, w, h):
        """Place a popup beside the mascot, on whichever side has more room."""
        mx, my = self.root.winfo_x(), self.root.winfo_y()
        left, top, right, bottom = work_area_at(mx + self.width // 2, my + self.height // 2)
        on_left = mx + self.width / 2 > (left + right) / 2
        x = mx + self.px(4) - w if on_left else mx + self.width
        y = my + self.height - h - self.px(10)
        x = min(max(x, left), right - w)
        y = min(max(y, top), bottom - h)
        return on_left, x, y

    def place_popups(self):
        if self.input.winfo_viewable():
            self.input.update_idletasks()
            _, x, y = self.popup_origin(self.input.winfo_reqwidth(), self.input.winfo_reqheight())
            self.input.geometry(f"+{x}+{y}")
        if self.bubble.winfo_viewable():
            self.draw_bubble()

    def reassert_topmost(self):
        for win in (self.root, self.input, self.bubble):
            if win.winfo_viewable():
                keep_on_top(win)
        self.root.after(1500, self.reassert_topmost)

    # ---- input box --------------------------------------------------------

    def build_input(self):
        win = self.input = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=PAPER, highlightthickness=max(1, self.px(1.5)),
                      highlightbackground=CLAY_DARK, highlightcolor=CLAY_DARK)
        # Mode switch across the top.
        modes = tk.Frame(win, bg=PAPER)
        modes.pack(fill="x", padx=self.px(8), pady=(self.px(7), self.px(2)))
        self.mode_buttons = {}
        for key in ("ask", "do"):
            b = tk.Label(modes, text=MODES[key]["label"], font=self.small_bold, padx=self.px(10),
                         pady=self.px(2), cursor="hand2")
            b.pack(side="left", padx=(0, self.px(6)))
            b.bind("<Button-1>", lambda e, k=key: self.set_mode(k))
            self.mode_buttons[key] = b
        self.mode_hint = tk.Label(modes, font=self.small, fg=MUTED, bg=PAPER)
        self.mode_hint.pack(side="left")

        self.entry = tk.Text(win, width=40, height=3, wrap="word", font=self.font, bd=0,
                             relief="flat", bg=PAPER, fg=INK, insertbackground=INK,
                             padx=self.px(10), pady=self.px(6), highlightthickness=0, undo=True)
        self.entry.pack(fill="both", expand=True)
        row = tk.Frame(win, bg=PAPER)
        row.pack(fill="x", padx=self.px(8), pady=(0, self.px(6)))
        tk.Label(row, text="Enter to send · Shift+Enter new line · Esc to close",
                 font=self.small, fg=MUTED, bg=PAPER).pack(side="left")
        self.link(row, "", self.submit, font=self.icons).pack(side="right")
        self.link(row, "", self.start_dictation, font=self.icons).pack(
            side="right", padx=(0, self.px(8)))
        self.entry.bind("<Return>", self.submit)
        self.entry.bind("<Shift-Return>", lambda e: None)
        win.bind("<Escape>", lambda e: self.hide_input())
        self.set_mode("ask")

    def set_mode(self, mode):
        self.mode = mode
        for key, button in self.mode_buttons.items():
            on = key == mode
            button.configure(bg=SEL_ON if on else SEL_OFF, fg=PAPER if on else MUTED)
        self.mode_hint.configure(text="quick answer, no tools" if mode == "ask"
                                 else "full tools and your context")

    def link(self, parent, text, command, font=None):
        label = tk.Label(parent, text=text, font=font or self.small, fg=CLAY_DARK, bg=PAPER,
                         cursor="hand2")
        label.bind("<Button-1>", lambda e: command())
        label.bind("<Enter>", lambda e: label.configure(fg=INK))
        label.bind("<Leave>", lambda e: label.configure(fg=CLAY_DARK))
        return label

    def toggle_input(self):
        if self.input.winfo_viewable():
            self.hide_input()
        else:
            self.open_input()

    def open_input(self, mode=None):
        if mode:
            self.set_mode(mode)
        if self.busy:  # a question is in flight; show its bubble instead
            self.show_bubble_window()
            return
        self.hide_bubble()
        self.input.deiconify()
        self.place_popups()
        self.input.lift()
        self.input.after(30, self.entry.focus_force)

    def hide_input(self):
        self.input.withdraw()

    def start_dictation(self):
        if self.busy:
            self.show_bubble_window()
            return
        if not self.input.winfo_viewable():
            self.open_input()
        self.input.after(60, self.entry.focus_force)
        self.input.after(300, press_win_h)

    def look_at_screen(self):
        """Capture the screen, then ask Do-it about it (it reads the image)."""
        if self.busy:
            self.show_bubble_window()
            return
        if not capture_screen(SCREEN_FILE):
            self.last_mode = "ask"
            self.show_reply("I couldn't capture the screen. Install Pillow (pip install pillow) "
                            "so Pip can see your screen.", error=True)
            return
        self.attach_screen = SCREEN_FILE.as_posix()
        self.open_input("do")

    def new_claude_session(self):
        """Open a fresh interactive Claude Code session in its own window."""
        cwd = str(GITHUB_DIR) if GITHUB_DIR.exists() else str(Path.home())
        cmd = session_launch_command(self.claude, shutil.which("wt") is not None, cwd)
        try:
            subprocess.Popen(cmd, cwd=cwd)
        except OSError as exc:
            log(f"could not start a session: {exc}")
            self.last_mode = "ask"
            self.show_reply(f"Couldn't start a Claude Code session: {exc}", error=True)

    # ---- asking Claude ----------------------------------------------------

    def submit(self, event=None):
        prompt = self.entry.get("1.0", "end").strip()
        if not prompt or self.busy:
            return "break"
        if not self.claude:
            self.hide_input()
            self.show_reply("I can't find the claude command. Install Claude Code and make "
                            "sure `claude` runs in a terminal.", error=True)
            return "break"
        self.entry.delete("1.0", "end")
        self.hide_input()
        model_prompt = prompt
        if self.attach_screen:
            self.set_mode("do")  # reading the screenshot needs Do-it's tools
            model_prompt = (f"Here is a screenshot of my current screen at {self.attach_screen}. "
                            f"Read it with the Read tool, then answer: {prompt}")
            self.attach_screen = None
        self.busy = True
        self.activity = "thinking"
        self.request_id += 1
        self.last_mode = self.mode
        self.started = time.monotonic()
        self.stream_buf = ""
        self.pending_prompt = prompt
        # Durable facts + recent exchanges, so Pip keeps continuity and its learned context.
        full = compose_prompt(load_learned(), load_recent_history(), model_prompt)
        start = "Working…" if self.last_mode == "do" else "Thinking…"
        self.set_bubble(start, thinking=True)
        self.show_bubble_window()
        threading.Thread(target=self.worker, args=(self.request_id, self.last_mode, full),
                         daemon=True).start()
        return "break"

    def worker(self, request_id, mode, prompt):
        def emit(event):
            self.events.put((request_id, event))
        try:
            stream_claude(self.claude, mode, prompt, self.remember_proc, emit)
        except Exception as exc:  # the UI must hear about every failure
            log(traceback.format_exc())
            emit(("result", False, f"Couldn't run claude: {exc}"))

    def remember_proc(self, proc):
        self.proc = proc

    def poll_events(self):
        grew = False
        try:
            while True:
                request_id, event = self.events.get_nowait()
                if request_id != self.request_id or not self.busy:
                    continue
                kind = event[0]
                if kind == "text":
                    self.stream_buf += event[1]
                    grew = True
                elif kind == "tool":
                    self.activity = "working"
                    self.set_stream_status(f"⚙ using {event[1]}…")
                elif kind == "result":
                    ok, text = event[1], event[2]
                    self.busy = False
                    self.proc = None
                    final = text or self.stream_buf.strip()
                    if ok and final:
                        self.last_reply = final
                        append_history(self.last_mode, self.pending_prompt, final)
                    self.show_reply(final or "No reply.", error=not ok)
                    grew = False
        except queue.Empty:
            pass
        if grew and self.busy:
            self.render_stream()
        self.root.after(80, self.poll_events)

    def cancel(self):
        if not self.busy:
            return
        self.busy = False
        self.request_id += 1
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.kill()

    # ---- speech bubble ----------------------------------------------------

    def build_bubble(self):
        win = self.bubble = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-transparentcolor", KEY)
        win.configure(bg=KEY)
        self.bcanvas = tk.Canvas(win, bg=KEY, highlightthickness=0, bd=0)
        self.bcanvas.pack()
        self.btext = tk.Text(self.bcanvas, wrap="word", font=self.font, bd=0, relief="flat",
                             bg=PAPER, fg=INK, padx=0, pady=0, highlightthickness=0,
                             cursor="arrow", selectbackground=HOVER, selectforeground=INK)
        self.btool = tk.Frame(self.bcanvas, bg=PAPER)
        self.bstatus = tk.Label(self.btool, font=self.small, fg=MUTED, bg=PAPER, anchor="w")
        self.bstatus.pack(side="left")
        self.link(self.btool, "Close", self.close_bubble).pack(side="right")
        self.copy_label = self.link(self.btool, "Copy", self.copy_reply)
        self.copy_label.pack(side="right", padx=(0, self.px(12)))
        win.bind("<Escape>", lambda e: self.close_bubble())

    def bubble_text_width(self):
        return self.px(340) - 2 * self.px(14)

    def set_bubble(self, text, thinking=False, error=False, status=""):
        text_w = self.bubble_text_width()
        lines = count_wrapped_lines(text, self.font, text_w - self.px(4))
        line_h = self.font.metrics("linespace")
        text_h = min(lines * line_h, self.px(360)) + self.px(2)
        self.bubble_state = {"thinking": thinking, "text_w": text_w, "text_h": text_h,
                             "drawn_h": text_h}
        t = self.btext
        t.configure(state="normal", fg=ERROR if error else (MUTED if thinking else INK))
        t.delete("1.0", "end")
        t.insert("1.0", text)
        t.configure(state="disabled")
        t.yview_moveto(1.0 if thinking else 0.0)
        self.bstatus.configure(text=status)
        if thinking:
            self.copy_label.pack_forget()
        elif not self.copy_label.winfo_ismapped():
            self.copy_label.pack(side="right", padx=(0, self.px(12)))
        self.copy_label.configure(text="Copy")
        self.draw_bubble()

    def render_stream(self):
        """Show the streamed-so-far text, growing the bubble and scrolling to the end."""
        text_w = self.bubble_text_width()
        lines = count_wrapped_lines(self.stream_buf, self.font, text_w - self.px(4))
        line_h = self.font.metrics("linespace")
        text_h = min(max(lines, 1) * line_h, self.px(360)) + self.px(2)
        s = self.bubble_state
        s.update(thinking=False, text_w=text_w, text_h=text_h)
        t = self.btext
        t.configure(state="normal", fg=INK)
        t.delete("1.0", "end")
        t.insert("1.0", self.stream_buf)
        t.configure(state="disabled")
        t.yview_moveto(1.0)
        elapsed = int(time.monotonic() - self.started)
        self.bstatus.configure(text=f"{MODES[self.last_mode]['label']} · {elapsed}s · Esc to cancel")
        if abs(text_h - s.get("drawn_h", 0)) >= line_h:  # only redraw geometry when it grows a line
            s["drawn_h"] = text_h
            self.draw_bubble()

    def set_stream_status(self, text):
        if self.bubble_state:
            self.bstatus.configure(text=text)

    def draw_bubble(self):
        s = self.bubble_state
        if not s:
            return
        pad, tail, radius, bar = self.px(14), self.px(12), self.px(14), self.px(24)
        body_w = s["text_w"] + 2 * pad
        body_h = pad + s["text_h"] + self.px(6) + bar + self.px(6)
        w, h = body_w + tail, body_h
        on_left, x, y = self.popup_origin(w, h)
        bx1 = 0 if on_left else tail
        bx2 = bx1 + body_w
        mascot_mid = self.root.winfo_y() + self.px(60)
        ty = min(max(mascot_mid - y, radius + self.px(10)), body_h - radius - self.px(10))

        c = self.bcanvas
        c.delete("all")
        c.configure(width=w, height=h)
        edge = max(1, self.px(1.5))
        c.create_polygon(*round_rect(bx1 + 1, 1, bx2 - 1, body_h - 2, radius), smooth=True,
                         fill=PAPER, outline=PAPER_EDGE, width=edge)
        spread = self.px(8)
        if on_left:
            base, tip = bx2 - edge - 1, w - 1
        else:
            base, tip = bx1 + edge + 1, 1
        c.create_polygon(base, ty - spread, tip, ty, base, ty + spread, fill=PAPER, outline="")
        c.create_line(base, ty - spread, tip, ty, base, ty + spread, fill=PAPER_EDGE, width=edge)
        c.create_window(bx1 + pad, pad, window=self.btext, anchor="nw",
                        width=s["text_w"], height=s["text_h"])
        c.create_window(bx1 + pad, body_h - self.px(6), window=self.btool, anchor="sw",
                        width=s["text_w"], height=bar)
        self.bubble.geometry(f"{w}x{h}+{x}+{y}")

    def show_reply(self, text, error=False):
        self.reaction = "error" if error else "happy"
        self.reaction_until = time.monotonic() + 2.5
        elapsed = time.monotonic() - self.started if self.started else 0
        if error:
            status = "Something went wrong"
        else:
            status = f"{MODES[self.last_mode]['verb']} · {elapsed:.0f}s"
        self.set_bubble(text, error=error, status=status)
        self.show_bubble_window()

    def show_bubble_window(self):
        if not self.bubble_state:
            return
        self.bubble.deiconify()
        self.draw_bubble()
        self.bubble.lift()
        self.bubble.focus_force()

    def hide_bubble(self):
        self.bubble.withdraw()

    def close_bubble(self):
        self.cancel()
        self.hide_bubble()

    def copy_reply(self):
        text = self.btext.get("1.0", "end").strip()
        if not text or (self.bubble_state and self.bubble_state["thinking"]):
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.copy_label.configure(text="Copied")
        self.root.after(1200, lambda: self.copy_label.configure(text="Copy"))

    def copy_last_reply(self):
        if self.last_reply:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.last_reply)

    # ---- menu and lifecycle -----------------------------------------------

    def build_menu(self):
        m = self.menu = tk.Menu(self.root, tearoff=False)
        m.add_command(label="Ask Claude…", command=lambda: self.open_input("ask"))
        m.add_command(label="Do it (full tools)…", command=lambda: self.open_input("do"))
        m.add_command(label="Look at my screen…", command=self.look_at_screen)
        m.add_command(label="Dictate (Win+H)", command=self.start_dictation)
        m.add_command(label="New Claude Code session", command=self.new_claude_session)
        m.add_separator()
        m.add_command(label="Show last reply", command=self.show_bubble_window)
        m.add_command(label="Copy last reply", command=self.copy_last_reply)
        m.add_separator()
        m.add_command(label="Reset position", command=self.reset_position)
        m.add_command(label="Quit", command=self.quit)

    def show_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)
        self.menu.grab_release()

    def report_error(self, *exc_info):
        log("".join(traceback.format_exception(*exc_info)))

    def quit(self):
        self.cancel()
        self.save_position()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    if already_running():
        return
    enable_dpi_awareness()
    try:
        Buddy().run()
    except Exception:
        log(traceback.format_exc())
        raise


if __name__ == "__main__":
    sys.exit(main())
