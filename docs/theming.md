# Theming Guide

Themes live at `themes/<name>/`. The renderer scans this directory for any subdir containing `theme.json` and treats it as a theme.

## Required files

```
themes/<your-theme>/
  theme.json
  route.html.tmpl
  quest-log.html.tmpl
  plan-card.html.tmpl
  landmarks/
    house.svg.tmpl   tower.svg.tmpl   mill.svg.tmpl
    bridge.svg.tmpl  camp.svg.tmpl    cave.svg.tmpl   castle.svg.tmpl
```

## theme.json

```json
{
  "name": "Your Theme",
  "version": "1.0",
  "positions": {
    "1": "translate(150,400)",
    "2": "translate(280,300)",
    "3": "translate(420,360)",
    "4": "translate(560,240)",
    "5": "translate(700,300)",
    "6": "translate(820,200)",
    "7": "translate(940,260)"
  }
}
```

`positions` keyed by quest `n` — the renderer applies the value as a `transform` attribute on the SVG group containing each landmark.

## Template syntax

```
{{var}}              — html-escaped substitution
{{{var}}}            — raw substitution (for embedded SVG)
{{path.dotted}}      — dotted property access
{{#each items}}…{{/each}}    — loop, items[i] available as `q`
{{#if field}}…{{/if}}        — conditional (truthy = render)
{{> partial-name}}            — include partial; theme dir first, then _shared/
```

Unmatched markers are left visible (`{{missing}}`) — easy to spot without crashing.

## Available scope (project view)

Top-level fields the renderer hoists onto the project scope:

- `id`, `name`, `subtitle`, `theme`, `level`, `level_roman`
- `xp` (`{current, max}`), `xp_pct`
- `counts` (`{done, current, locked, total}`)
- `quests` — full list with derivations
- `active` — current quest (or empty placeholder)
- `active_progress_pct` — int 0-100
- `tasks`, `tasks_done`, `tasks_total`, `branch`, `last_commit`, `last_touched`, `last_touched_human`, `why`, `kpi`, `blockers_str`, `tags_str`, `depends_on`, `links`, `effort`, `progress_pct` — hoisted from active quest if present

## Per-quest scope (inside `{{#each quests}}`)

- `q.id`, `q.n`, `q.name`, `q.desc`, `q.status`, `q.status_class`
- `q.progress_pct`, `q.xp_str`, `q.xp_reward`, `q.roman`
- `q.transform` — position from theme.json
- `q.landmark_svg` — raw SVG content for the landmark (use with `{{{q.landmark_svg}}}`)
- `q.has_next` — bool (next_step non-empty AND status=current)
- `q.tasks`, `q.tasks_done`, `q.tasks_total`, `q.branch`, `q.last_commit`, etc. — same as project scope but per-quest

## Shared partials

`themes/_shared/` provides theme-agnostic structure:

| Partial | What it renders | Required CSS classes |
|---|---|---|
| `_back-link` | "← All Projects" link | `.qd-back-link` |
| `_taskslist` | Tasks checklist (renders if non-empty) | `.qd-tasks`, `.qd-task`, `.qd-task-done`, `.qd-task-todo` |
| `_meta-row` | Branch / commit / why / KPI / tags / blockers rows | `.qd-meta`, `.qd-meta-row` |
| `_progress-bar` | Progress bar (uses `progress_pct`) | `.qd-progress`, `.qd-progress-fill`, `.qd-progress-label` |

Override any partial by placing a same-named file in your theme dir.

## Quick test

```bash
python3 ~/.claude/skills/quest/render.py --dry-run
python3 ~/.claude/skills/quest/quest.py theme <project-id> <your-theme>
xdg-open http://localhost:8770/<project-id>/route.html
```

If you see literal `{{tokens}}` in output, that's a substitution miss — check spelling against the scope tables above.
