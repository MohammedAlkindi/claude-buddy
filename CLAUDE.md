# claude-buddy

## Stack
Python 3 (Windows 11 only): one `tkinter` file, `buddy.pyw`, standard library only.

## Commands
- Install: none (standard library only)
- Run: `pythonw buddy.pyw` (use `python buddy.pyw` to see tracebacks in a console)
- Test: `python -m unittest discover -s tests -v`

## Modes
The pencil has two modes, chosen in the input box. Both stream the reply.
- **Ask** (default): `claude --safe-mode --tools ""` — no tools, no context load, cannot touch files or accounts. Fast quick answers.
- **Do it**: `claude --permission-mode bypassPermissions --chrome --add-dir ~/Github`, cwd `~/Github` — full tools, connectors, dotgithub context, and Claude in Chrome (his real signed-in browser) for website tasks, running unattended. It can change things on the machine, so it is never the default. The system prompt tells it to use Claude in Chrome for web work, never to hide the automation or bypass sign-ins/bot checks, and to avoid irreversible/outward actions it was not asked for.

Both are defined in `MODES`; change flags there, not scattered through the code.

Do-it finds documents through the Google Drive connector (his docs live in Drive). The right-click menu's **New Claude Code session** opens a fresh interactive `claude` in Windows Terminal (or a console), built by the pure `session_launch_command()`.

## Rules
- No hardcoded secrets or API keys anywhere. Claude calls go through the `claude` CLI login; `claude_env()` strips API keys so calls never bill per token.
- The only external call is `stream_claude()`; it emits `("text", ...)`, `("tool", name)`, `("result", ok, text)` events and never raises to the UI. `parse_stream_line()` turns one stream-json line into those events.
- Keep helpers that need no Tk (`count_wrapped_lines`, `claude_env`, `parse_stream_line`, `round_rect`) pure and unit-tested.
- Never block the Tk thread: the subprocess is read on a worker thread and reports back through the events queue, drained by `poll_events`.
- No pip dependencies without a reason: Smart App Control on this machine blocks fresh unsigned binaries and some wheels.
- One logical change per commit; never commit with tests failing.
