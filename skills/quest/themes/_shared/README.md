# Shared Partials

These are theme-agnostic structural partials — pure semantic HTML with `qd-*` class hooks. Each theme provides its own CSS to style them via the main view template's `<style>` block.

## How partials resolve

`{{> partial-name}}` looks up `<theme>/<name>.html.tmpl` first, then falls back to `_shared/<name>.html.tmpl`. To override: drop a same-named file into your theme's directory.

## Available partials

| Partial | Scope keys it consumes | Renders when |
|---|---|---|
| `_back-link` | (none) | Always |
| `_taskslist` | `tasks[]` (with `done_class`, `done_mark`), `tasks_done`, `tasks_total` | `tasks` non-empty |
| `_meta-row` | `branch`, `last_commit.{sha,msg,date}`, `last_touched_human`, `why`, `kpi`, `tags_str`, `blockers_str` | Each row independently — only resolved fields render |
| `_progress-bar` | `progress_pct` (int 0-100) | Always |

## Class hooks (CSS contract)

Themes MUST style at least:
- `.qd-back-link` — back nav link
- `.qd-tasks`, `.qd-task`, `.qd-task-done`, `.qd-task-todo` — checklist
- `.qd-meta`, `.qd-meta-row` — meta rows
- `.qd-progress`, `.qd-progress-fill`, `.qd-progress-label` — progress bar

Themes that ship without CSS for these classes will render unstyled but still functional.

## Adding a new partial

1. Add `_<name>.html.tmpl` here
2. Document scope keys in this README
3. Reference via `{{> _name}}` in any template
4. Themes can override by dropping same-named file in their dir
