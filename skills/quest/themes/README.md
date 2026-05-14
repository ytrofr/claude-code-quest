# Themes — adding a new style

A theme is a directory under `~/.claude/skills/quest/themes/<name>/`. The renderer auto-discovers any directory containing a valid `theme.json`.

## Required files

```
themes/<your-theme>/
  theme.json                          # metadata (name, positions, landmark list)
  route.html.tmpl                     # the world map view
  quest-log.html.tmpl                 # quest list/grid view
  plan-card.html.tmpl                 # single-quest detail view
  landmarks/
    house.svg.tmpl                    # SVG snippet (no <svg> wrapper, no <g> wrapper)
    tower.svg.tmpl
    mill.svg.tmpl
    bridge.svg.tmpl
    camp.svg.tmpl
    cave.svg.tmpl
    castle.svg.tmpl
```

## theme.json shape

```json
{
  "name": "your-theme",
  "version": 1,
  "description": "Short tagline",
  "font": "Google Font Name",
  "landmarks": ["house","tower","mill","bridge","camp","cave","castle"],
  "positions": {
    "1": "translate(80,460)",
    "2": "translate(280,380)",
    "3": "translate(460,320)",
    "4": "translate(640,320)",
    "5": "translate(820,280)",
    "6": "translate(960,180)",
    "7": "translate(1080,90)"
  }
}
```

`positions` maps quest index (1..7) → SVG transform. The renderer uses these to place each quest's marker on your map.

## Template syntax

The renderer is hand-rolled regex substitution. Three constructs:

| Form | Meaning |
|---|---|
| `{{var}}` | HTML-escaped substitution |
| `{{{var}}}` | Raw substitution (use for SVG blobs like `{{{q.landmark_svg}}}`) |
| `{{#each quests}}…{{/each}}` | Repeat block per quest. Inside, use `{{q.field}}` for quest fields and `{{{q.landmark_svg}}}` for the landmark SVG. |

### Top-level scope (project)

- `{{name}}`, `{{subtitle}}`, `{{theme}}`, `{{level}}`, `{{level_roman}}`
- `{{xp.current}}`, `{{xp.max}}`, `{{xp_pct}}`
- `{{counts.done}}`, `{{counts.current}}`, `{{counts.locked}}`, `{{counts.total}}`
- `{{active.name}}`, `{{active.desc}}`, `{{active.next_step}}`, `{{active.n}}`, `{{active.xp_reward}}`, `{{active.plan}}`, `{{{active.landmark_svg}}}`
- `{{active_progress_pct}}`

### Quest scope (inside `{{#each quests}}`)

- `{{q.id}}`, `{{q.n}}`, `{{q.name}}`, `{{q.desc}}`
- `{{q.status_class}}` — one of `done|current|locked`
- `{{q.progress_pct}}` — int 0-100
- `{{q.xp_reward}}`, `{{q.xp_str}}` (e.g. "+25 XP")
- `{{q.roman}}` — Roman numeral
- `{{q.transform}}` — SVG transform from `theme.json` `positions[q.n]`
- `{{{q.landmark_svg}}}` — raw landmark SVG content
- `{{q.plan}}`, `{{q.next_step}}`, `{{q.has_next}}`

## Status visibility (CSS pattern)

Show different elements per status with CSS classes:

```css
.qm-locked { opacity: 0.6; }
.badge-done, .badge-current { display: none; }
.qm-done .badge-done { display: block; }
.qm-current .badge-current { display: block; }
```

Wrap each quest marker with `class="qm qm-{{q.status_class}}"`.

## Landmark SVG conventions

Each landmark file contains SVG content (no outer `<svg>` or `<g>` — those come from the route template's each-block wrapper). Coordinates relative to (0,0) which is the quest's anchor point on the path. Examples:

```svg
<!-- house.svg.tmpl: a small dwelling -->
<rect x="-22" y="-2" width="44" height="24" fill="#d65a3a" stroke="#5a2418" stroke-width="3"/>
<polygon points="-26,-2 0,-22 26,-2" fill="#a83a20" stroke="#5a2418" stroke-width="3"/>
```

Keep the visual extent within roughly ±32px wide / -50px to 30px tall so labels and badges fit.

## Test your theme

```bash
# Check theme is discovered
python3 ~/.claude/skills/quest/quest.py status

# Apply to a project
python3 ~/.claude/skills/quest/quest.py theme apollo your-theme

# Open the rendered map
xdg-open http://localhost:8770/apollo/route.html
```

If the renderer leaves `{{token}}` markers visible in the output, that's a substitution miss — check the spelling against the scope tables above.
