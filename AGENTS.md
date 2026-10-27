# Agents: claude-buddy

## Scope
Agents may edit source, tests, and docs in this repo.

## Branch policy
- Mohammed owns this repo: commit straight to `main` with his configured identity and no AI trailers.
- Use a `claude/<kebab>` branch only when a change needs review before it lands.

## Requires confirmation
- Adding dependencies or changing test tooling.
- Adding a startup shortcut (`shell:startup`) or any other change outside this folder.
- Deleting files or history-rewriting operations.

## Never
- Commit failing tests. Commit secrets. Force-push.
- Drive the real mouse or keyboard to test the UI while Mohammed is using the machine. Construct a second `Buddy()` in a script and call its methods instead.
