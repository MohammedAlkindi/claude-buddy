# claude-buddy

## What it does
Pip is a small mascot that floats on top of your Windows desktop, even over Zoom. Click the pencil, type a question, and Claude's reply appears in a speech bubble next to Pip. The mic button starts Windows voice typing so you can dictate the question.

## Architecture
Everything lives in one file, `buddy.pyw`, which uses Python's built-in `tkinter`. No packages to install.

- **Mascot window:** a frameless, always-on-top window with a transparent background. Pip is drawn on a canvas. Drag Pip to move it. The position is saved to `%LOCALAPPDATA%\claude-buddy\state.json`.
- **Asking Claude:** each question runs `claude -p` (the Claude Code CLI) on a background thread, so the window never freezes. It uses your Claude login. API keys are removed from the CLI's environment, so you are never billed per call. `--safe-mode` and `--tools ""` keep it a fast, chat-only call. Change `CLAUDE_ARGS` at the top of the file to adjust this.
- **Speech bubble:** shows the reply with Copy and Close buttons. Esc closes it, and also cancels a question that is still running.
- **Mic:** opens the text box, focuses it, and presses Win+H for Windows voice typing.
- **Right-click Pip:** Ask, Dictate, Show or Copy the last reply, Reset position, Quit.

Errors are logged to `%LOCALAPPDATA%\claude-buddy\buddy.log`. Only one Pip runs at a time.

## Setup
Requires Windows 11, Python 3.10 or later, and Claude Code with a working login (`claude` runs in a terminal).

```
git clone https://github.com/MohammedAlkindi/claude-buddy.git
cd claude-buddy
pythonw buddy.pyw
```

To start Pip when you sign in, put a shortcut to `pythonw.exe "<path>\buddy.pyw"` in the folder that `shell:startup` opens.

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
