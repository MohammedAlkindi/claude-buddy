# claude-buddy

## Stack
Python 3 (Windows 11 only): one `tkinter` file, `buddy.pyw`, standard library only.

## Commands
- Install: none (standard library only)
- Run: `pythonw buddy.pyw` (use `python buddy.pyw` to see tracebacks in a console)
- Test: `python -m unittest discover -s tests -v`

## Rules
- No hardcoded secrets or API keys anywhere. Claude calls go through the `claude` CLI login; `claude_env()` strips API keys so calls never bill per token.
- The only external call is `run_claude()`; it returns `(ok, text)` and never raises to the UI.
- Keep helpers that need no Tk (`count_wrapped_lines`, `claude_env`, `run_claude`, `round_rect`) pure and unit-tested.
- Never block the Tk thread: subprocess work runs on a worker thread and reports back through the results queue.
- No pip dependencies without a reason: Smart App Control on this machine blocks fresh unsigned binaries and some wheels.
- One logical change per commit; never commit with tests failing.
