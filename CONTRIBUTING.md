# Contributing to Claude Code Quest

Thanks for considering a contribution. This project has one strong opinion: **zero dependencies, zero LLM calls, localhost-only.** Anything that needs `npm install`, a cloud service, or an API token belongs in a different project.

## What's welcome

- **New themes** — drop a folder under `skills/quest/themes/<name>/` with a `theme.json`, three view templates (`route`, `quest-log`, `plan-card`), and seven landmark SVGs. The renderer auto-discovers it. See `docs/theming.md` and the existing `pokemon` / `storybook` themes.
- **Renderer fixes** — the template engine is hand-rolled (~430 LOC, `render.py`). Bug fixes welcome; keep it dependency-free.
- **Parser improvements** — `autosync.py` parses plan-file checkboxes; `sidecar.py` parses the My To-Do sidecar. Both are pure-function and have test files alongside them.
- **Docs** — clearer install steps, more FAQ entries, better theming guide.

## What's out of scope

- JS frameworks, build steps, bundlers
- Server-side anything beyond the static `http.server`
- LLM-driven features — progress is pure markdown parsing, on purpose
- Remote sync / accounts / multi-user — Quest is a personal, offline tool

## Before you open a PR

1. **Run the tests** — the engine has standalone test files:
   ```bash
   cd skills/quest
   for t in test_*.py; do python3 "$t"; done
   ```
   All assertions must pass. New behavior needs a new test.
2. **Keep it zero-dep** — `python3` standard library only. No `pip install`.
3. **No personal data** — the public repo ships only fictional example data (`apollo`, `atlas`, `nova`). Don't add real project names, paths, or identifiers.
4. **Match the existing style** — follow the conventions in the file you're editing.

## Reporting bugs / requesting features

- Bug: open a [bug report](https://github.com/ytrofr/claude-code-quest/issues/new?template=bug_report.yml)
- Idea: file a [feature request](https://github.com/ytrofr/claude-code-quest/issues/new?template=feature_request.yml)

Include your OS, Python version, and the commit SHA you're on.

## License

By contributing, you agree your contributions are licensed under the MIT License (see `LICENSE`).
