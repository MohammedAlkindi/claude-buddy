"""Claude Buddy: a floating desktop mascot that puts `claude -p` one click away.

Run with `pythonw buddy.pyw`. The pencil asks a question, the mic starts
Windows voice typing (Win+H), right-click opens the menu. Replies come from the
Claude Code CLI, so they use your Claude login rather than an API key.
"""

import ctypes
import json
import math
import os
import queue
import random
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

# Not %LOCALAPPDATA%: a Pip started from an MSIX app (such as the Claude desktop
# app) would write into that app's private copy of AppData, and a Pip started at
# sign-in would never see it.
APP_DIR = Path.home() / ".local" / "state" / "claude-buddy"
STATE_FILE = APP_DIR / "state.json"
LOG_FILE = APP_DIR / "buddy.log"

# --safe-mode skips CLAUDE.md, hooks, plugins and MCP servers so a quick
# question starts fast; --tools "" keeps the buddy chat-only.
CLAUDE_ARGS = [
    "-p",
    "--safe-mode",
    "--no-session-persistence",
    "--tools", "",
    "--append-system-prompt",
    "You are answering inside a small desktop speech bubble. Keep replies "
    "short and write plain text without Markdown formatting.",
]
CLAUDE_TIMEOUT = 300

KEY = "#ff00ff"  # transparent color key; never used in the drawing
MINT = "#86dcb8"
MINT_SHEEN = "#bdeed8"
MINT_DARK = "#2f8f6c"
LEAF = "#5cc48f"
INK = "#1f2a30"
CHEEK = "#f4a6b8"
PAPER = "#ffffff"
PAPER_EDGE = "#c3d3cc"
HOVER = "#e3f5ec"
MUTED = "#6b7b74"
ERROR = "#b3261e"

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


def run_claude(exe, prompt, on_start):
    proc = subprocess.Popen(
        [exe, *CLAUDE_ARGS],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        env=claude_env(), cwd=str(Path.home()),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    on_start(proc)
    try:
        out, err = proc.communicate(prompt, timeout=CLAUDE_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return False, "Claude took longer than 5 minutes, so I stopped it."
    if proc.returncode == 0 and out.strip():
        return True, out.strip()
    return False, (err or out).strip() or f"claude exited with code {proc.returncode}"


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
        self.results = queue.Queue()
        self.proc = None
        self.busy = False
        self.request_id = 0
        self.started = 0.0
        self.last_reply = ""
        self.bubble_state = None
        self.press = None
        self.tick_count = 0
        self.bob = 0
        self.next_blink = 40

        families = set(tkfont.families(self.root))
        icon_family = "Segoe Fluent Icons" if "Segoe Fluent Icons" in families else "Segoe MDL2 Assets"
        self.font = tkfont.Font(self.root, family="Segoe UI", size=10)
        self.small = tkfont.Font(self.root, family="Segoe UI", size=8)
        self.icons = tkfont.Font(self.root, family=icon_family, size=11)

        self.build_mascot()
        self.build_input()
        self.build_bubble()
        self.build_menu()
        self.restore_position()

        self.root.after(60, self.tick)
        self.root.after(100, self.poll_results)
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
        self.width, self.height = self.px(134), self.px(118)
        c = self.canvas = tk.Canvas(root, width=self.width, height=self.height,
                                    bg=KEY, highlightthickness=0, bd=0)
        c.pack()
        line = max(2, self.px(2.5))

        # Pip: a round mint sprout with stubby feet. Everything tagged "body" bobs.
        for x in (30, 60):
            c.create_oval(*self.xy(x, 100, x + 16, 112), fill=MINT_DARK, outline="", tags="body")
        c.create_line(*self.xy(52, 30, 52, 15), fill=MINT_DARK, width=line, tags="body")
        c.create_polygon(*self.xy(53, 18, 58, 7, 71, 3, 67, 13, 55, 19), smooth=True,
                         fill=LEAF, outline=MINT_DARK, width=max(1, self.px(1.5)), tags="body")
        c.create_polygon(*self.xy(51, 19, 46, 11, 36, 10, 40, 17, 50, 21), smooth=True,
                         fill=LEAF, outline=MINT_DARK, width=max(1, self.px(1.5)), tags="body")
        c.create_oval(*self.xy(10, 28, 94, 108), fill=MINT, outline=MINT_DARK, width=line,
                      tags=("body", "hit"))
        c.create_oval(*self.xy(24, 40, 40, 51), fill=MINT_SHEEN, outline="", tags=("body", "hit"))
        for x in (35, 58):
            c.create_oval(*self.xy(x, 56, x + 11, 72), fill=INK, outline="",
                          tags=("body", "hit", "eye_open"))
            c.create_oval(*self.xy(x + 3, 59, x + 7, 63), fill=PAPER, outline="",
                          tags=("body", "hit", "eye_open"))
            c.create_line(*self.xy(x, 65, x + 11, 65), fill=INK, width=line,
                          state="hidden", tags=("body", "hit", "eye_closed"))
        for x in (24, 70):
            c.create_oval(*self.xy(x, 72, x + 10, 78), fill=CHEEK, outline="", tags=("body", "hit"))
        c.create_arc(*self.xy(45, 68, 59, 80), start=200, extent=140, style="arc",
                     outline=INK, width=max(1, self.px(2)), tags=("body", "hit", "smile"))
        c.create_oval(*self.xy(49, 74, 55, 80), fill=INK, outline="", state="hidden",
                      tags=("body", "hit", "mouth_o"))
        for i, (x, y, r) in enumerate(((74, 22, 3), (82, 14, 4), (92, 5, 5))):
            c.create_oval(*self.xy(x - r, y - r, x + r, y + r), fill=PAPER, outline=MINT_DARK,
                          width=max(1, self.px(1.5)), state="hidden", tags=("body", f"dot{i}"))

        self.add_button("pencil", 102, 34, "")
        self.add_button("mic", 102, 72, "")

        c.tag_bind("hit", "<Enter>", lambda e: c.configure(cursor="fleur"))
        c.tag_bind("hit", "<Leave>", lambda e: c.configure(cursor=""))
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Button-3>", self.show_menu)
        root.bind("<Escape>", lambda e: self.close_bubble())

    def add_button(self, name, x, y, glyph):
        c = self.canvas
        tag = f"btn_{name}"
        circle = c.create_oval(*self.xy(x, y, x + 28, y + 28), fill=PAPER, outline=MINT_DARK,
                               width=max(1, self.px(1.5)), tags=(tag, "button"))
        c.create_text(*self.xy(x + 14, y + 14), text=glyph, font=self.icons, fill=MINT_DARK,
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
        elif p["target"] == "pencil":
            self.toggle_input()
        elif p["target"] == "mic":
            self.start_dictation()
        else:
            self.toggle_input()

    def tick(self):
        self.tick_count += 1
        t = self.tick_count
        c = self.canvas
        offset = round(math.sin(t * 0.1) * self.px(2))
        if offset != self.bob:
            c.move("body", 0, offset - self.bob)
            self.bob = offset
        if self.busy:
            shown = (t // 6) % 4
            for i in range(3):
                c.itemconfigure(f"dot{i}", state="normal" if i < shown else "hidden")
            if t % 6 == 0 and self.bubble_state and self.bubble_state["thinking"]:
                self.update_thinking()
        elif t >= self.next_blink:
            c.itemconfigure("eye_open", state="hidden")
            c.itemconfigure("eye_closed", state="normal")
            self.root.after(140, self.open_eyes)
            self.next_blink = t + random.randint(45, 110)
        self.root.after(60, self.tick)

    def open_eyes(self):
        self.canvas.itemconfigure("eye_closed", state="hidden")
        self.canvas.itemconfigure("eye_open", state="normal")

    def set_thinking_face(self, thinking):
        c = self.canvas
        c.itemconfigure("smile", state="hidden" if thinking else "normal")
        c.itemconfigure("mouth_o", state="normal" if thinking else "hidden")
        if not thinking:
            for i in range(3):
                c.itemconfigure(f"dot{i}", state="hidden")

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
                      highlightbackground=MINT_DARK, highlightcolor=MINT_DARK)
        self.entry = tk.Text(win, width=38, height=3, wrap="word", font=self.font, bd=0,
                             relief="flat", bg=PAPER, fg=INK, insertbackground=INK,
                             padx=self.px(10), pady=self.px(8), highlightthickness=0, undo=True)
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

    def link(self, parent, text, command, font=None):
        label = tk.Label(parent, text=text, font=font or self.small, fg=MINT_DARK, bg=PAPER,
                         cursor="hand2")
        label.bind("<Button-1>", lambda e: command())
        label.bind("<Enter>", lambda e: label.configure(fg=INK))
        label.bind("<Leave>", lambda e: label.configure(fg=MINT_DARK))
        return label

    def toggle_input(self):
        if self.input.winfo_viewable():
            self.hide_input()
        else:
            self.open_input()

    def open_input(self):
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
        self.busy = True
        self.request_id += 1
        self.started = time.monotonic()
        self.set_thinking_face(True)
        self.set_bubble("Thinking", thinking=True)
        self.show_bubble_window()
        threading.Thread(target=self.worker, args=(self.request_id, prompt), daemon=True).start()
        return "break"

    def worker(self, request_id, prompt):
        try:
            ok, text = run_claude(self.claude, prompt, self.remember_proc)
        except Exception as exc:  # the UI must hear about every failure
            log(traceback.format_exc())
            ok, text = False, f"Couldn't run claude: {exc}"
        self.results.put((request_id, ok, text))

    def remember_proc(self, proc):
        self.proc = proc

    def poll_results(self):
        try:
            while True:
                request_id, ok, text = self.results.get_nowait()
                if request_id == self.request_id and self.busy:
                    self.busy = False
                    self.proc = None
                    self.set_thinking_face(False)
                    if ok:
                        self.last_reply = text
                    self.show_reply(text, error=not ok)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_results)

    def cancel(self):
        if not self.busy:
            return
        self.busy = False
        self.request_id += 1
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.kill()
        self.set_thinking_face(False)

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

    def set_bubble(self, text, thinking=False, error=False, status=""):
        text_w = self.px(340) - 2 * self.px(14)
        lines = count_wrapped_lines(text, self.font, text_w - self.px(4))
        line_h = self.font.metrics("linespace")
        text_h = min(lines * line_h, self.px(360)) + self.px(2)
        self.bubble_state = {"thinking": thinking, "text_w": text_w, "text_h": text_h}
        t = self.btext
        t.configure(state="normal", fg=ERROR if error else (MUTED if thinking else INK))
        t.delete("1.0", "end")
        t.insert("1.0", text)
        t.configure(state="disabled")
        t.yview_moveto(0)
        self.bstatus.configure(text=status)
        if thinking:
            self.copy_label.pack_forget()
        elif not self.copy_label.winfo_ismapped():
            self.copy_label.pack(side="right", padx=(0, self.px(12)))
        self.copy_label.configure(text="Copy")
        self.draw_bubble()

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
        mascot_mid = self.root.winfo_y() + self.px(66)
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

    def update_thinking(self):
        dots = "." * ((self.tick_count // 6) % 4)
        elapsed = int(time.monotonic() - self.started)
        t = self.btext
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", "Thinking" + dots)
        t.configure(state="disabled")
        self.bstatus.configure(text=f"Asking Claude · {elapsed}s · Esc to cancel")

    def show_reply(self, text, error=False):
        elapsed = time.monotonic() - self.started if self.started else 0
        status = "Something went wrong" if error else f"Claude · {elapsed:.0f}s"
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
        m.add_command(label="Ask Claude…", command=self.open_input)
        m.add_command(label="Dictate (Win+H)", command=self.start_dictation)
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
