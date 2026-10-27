# claude-buddy

## What it does
Pip is a small mascot that floats on top of your Windows desktop, even over Zoom. Click the pencil, type a question, and Claude's reply appears in a speech bubble next to Pip. The mic button starts Windows voice typing so you can dictate the question.

## Architecture
Everything lives in one file, `buddy.pyw`, which uses Python's built-in `tkinter`. No packages to install.

- **Mascot window:** a frameless, always-on-top window with a transparent background. Pip has a rounded terracotta hood, a dark terminal face, and a little hoodie. Canvas-drawn animation includes breathing, blinking, greetings, thinking, working, dragging, and brief success/error reactions. Drag Pip to move it. The position is saved to `~\.local\state\claude-buddy\state.json`.
- **Asking Claude:** each question runs `claude -p` (the Claude Code CLI) on a background thread, so the window never freezes. It uses your Claude login. Ask mode uses `--safe-mode` and `--tools ""` for chat; Do it enables tools. Change `MODES` near the top of the file to adjust flags and timeouts. The deadline covers the whole streaming request, including a silent process or blocked prompt input. Thinking dots disappear after completion or cancellation.
- **Speech bubble:** shows the reply with Copy and Close buttons. Esc closes it, and also cancels a question that is still running.
- **Mic:** opens the text box, focuses it, and presses Win+H for Windows voice typing.
- **Right-click Pip:** Ask, Dictate, Show or Copy the last reply, Reset position, Quit.

Errors are logged to `~\.local\state\claude-buddy\buddy.log`. State stays out of AppData on purpose. If Pip is started from inside an MSIX-packaged app (such as the Claude desktop app), its AppData writes go to that app's private copy and are lost to every other launch. Only one Pip runs at a time.

## Setup
Requires Windows 11, Python 3.10 or later, and Claude Code with a working login (`claude` runs in a terminal).

```
git clone https://github.com/MohammedAlkindi/claude-buddy.git
cd claude-buddy
pythonw buddy.pyw
```

To start Pip when you sign in, put a shortcut to `pyw.exe "<path>\buddy.pyw"` in the folder that `shell:startup` opens. Create it from Explorer or a normal terminal. Created from inside the Claude desktop app, it lands in the app's private copy of AppData and never runs.

## Environment variables
None. Pip uses the login that the `claude` CLI already has. It strips `ANTHROPIC_API_KEY` and similar variables from the CLI's environment so calls always go through your Claude plan.

| Var | Purpose | Where to get it |
| --- | ------- | --------------- |
| (none) | | |

## Tests
```
python -m unittest discover -s tests -v
```
The tests cover text wrapping, the cleaned CLI environment and reply handling. They use a stand-in executable, so no real Claude call is made.
