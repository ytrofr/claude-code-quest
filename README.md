# claude-code-gamify

> Turn your `~/.claude/` projects into an RPG. Track plans as quests on themed maps. Localhost dashboard, auto-progress from plan checkboxes, drop-in themes — all engine, no AI tokens.

**Live demo URL** (after install): <http://localhost:8770>

---

## Why this exists

If you're juggling 3+ codebases under Claude Code, you're losing track of what's done, what's blocked, and what's next. Plans live in `~/.claude/plans/*.md`, statuses in your head, branches in tabs. This repo turns that into a single visual roadmap with two themes:

- **Pokémon Route** — top-down regional map, trainer pawn, cartoon SVG landmarks (Fredoka)
- **Storybook** — illuminated parchment spread, watercolor terrain, illuminated capitals (Eczar)

Each project becomes a region; each plan becomes a quest with status (done/current/locked), tasks, KPI, branch, last commit, dependencies.

## What's in the box

| Component | What |
|---|---|
| `/quest` skill | `status`, `add`, `update`, `done`, `theme`, `render`, `init` subcommands |
| Hand-rolled renderer | Zero-dep Python (~250 LOC). `{{var}}`, `{{#each}}`, `{{#if}}`, `{{> partial}}` |
| Two ready themes | Pokémon + Storybook, each with 3 views × 7 landmark SVGs |
| Shared partials | `_back-link`, `_taskslist`, `_meta-row`, `_progress-bar` — drop-in modular |
| Auto-progress hook | PostToolUse async, parses `## Section 13` checkboxes from plan markdown — **zero LLM calls** |
| systemd unit | localhost service on :8770, auto-starts on boot, hardened (`ProtectSystem=strict`) |

## Install

```bash
git clone https://github.com/ytrofr/claude-code-gamify ~/claude-code-gamify
cd ~/claude-code-gamify
./install.sh
```

Then:
1. Edit `~/.claude/quest/config.json` to add your real project paths
2. Wire the hook in `~/.claude/settings.json` (see below)
3. Open <http://localhost:8770/>

### Wiring the hook

Add to `~/.claude/settings.json` under `hooks.PostToolUse`:

```json
{
  "matcher": "Write|Edit",
  "hooks": [
    {"type": "command", "command": "/home/YOU/.claude/hooks/quest-plan-autosync.sh", "async": true}
  ]
}
```

The hook only fires on writes to paths matching `*/plans/*.md` or `*/.claude/plans/*.md` — everything else exits in microseconds.

## How it works

```
┌─────────────────────┐    write plan    ┌──────────────────────┐
│  ~/.claude/plans/   │ ───────────────> │ quest-plan-autosync  │  (PostToolUse async)
│  <feature>.md       │                  │     ~30ms / no LLM   │
└─────────────────────┘                  └──────────┬───────────┘
                                                    │
                                                    v
                                ┌────────────────────────────────────┐
                                │    autosync.py                     │
                                │    1. resolve project (BLUF/path)  │
                                │    2. parse §13 checkboxes         │
                                │    3. extract git branch + commit  │
                                │    4. update or add quest          │
                                │    5. trigger render               │
                                └─────────────────────┬──────────────┘
                                                      │
                                                      v
┌────────────────────┐                 ┌──────────────────────────┐
│ quests.json (v2)   │ <─── source ─── │ render.py                │
│ central truth      │                 │ → site/<id>/{route,log,  │
└────────────────────┘                 │           plan-card}.html│
                                       └──────────────┬───────────┘
                                                      │
                                                      v
                                           localhost:8770 (systemd)
```

## Themes — drop-in extensible

Adding a third theme is dropping a folder. The renderer scans `themes/*/theme.json`. Each theme provides:

```
themes/<name>/
  theme.json          # { name, version, positions: { "1": "translate(x,y)", ... } }
  route.html.tmpl     # full-page map view
  quest-log.html.tmpl # listing view
  plan-card.html.tmpl # per-quest detail
  landmarks/
    house.svg.tmpl   tower.svg.tmpl   mill.svg.tmpl
    bridge.svg.tmpl  camp.svg.tmpl    cave.svg.tmpl   castle.svg.tmpl
```

Shared partials (`themes/_shared/_*.html.tmpl`) cover the cross-theme structure — themes provide CSS for the `qd-*` class hooks. See `skills/quest/themes/README.md`.

## Data schema (v2)

`quests.json` per-quest, all v2 fields optional:

| Field | Type | Source |
|---|---|---|
| `id`, `n`, `name`, `desc`, `landmark`, `status`, `progress`, `xp_reward`, `plan`, `next_step` | core | hand-set or `/quest` |
| `tasks[]` | `[{title, done}]` | auto-parsed from plan §13 checkboxes |
| `last_touched` | ISO8601 | auto-set by autosync |
| `branch`, `last_commit{sha,msg,date}` | git | auto-pulled from local repo |
| `why`, `kpi` | string | hand-set |
| `blockers[]`, `tags[]`, `depends_on[]`, `links[{project,quest}]` | arrays | hand-set |
| `effort{estimate_hr,actual_hr}` | object | hand-set |

See `examples/quests.json` for fully-populated samples (apollo, atlas, nova).

## Natural-language triggers (with Claude Code)

Once installed, an auto-loaded rule teaches Claude to recognize:

| You say | Claude runs |
|---|---|
| "what's the status of apollo?" | `/quest status` + cites the URL |
| "mark X done" | `/quest done <project> <id>` |
| "switch atlas to pokemon theme" | `/quest theme atlas pokemon` |
| Write a plan with `**Project**: <id>` BLUF | quest auto-appears, no command needed |

## Architecture choices (and what we said NO to)

- ✅ Zero-dep Python renderer — no jinja, no node, no build step
- ✅ Static HTML output — `python3 -m http.server` is enough; no Flask/FastAPI
- ✅ systemd-managed service — restart, logging, lifecycle handled
- ✅ Local-only dashboard — bound to 127.0.0.1; no external surface
- ❌ No tiered XP — flat 25 per quest, cosmetic only
- ❌ No LLM-driven progress — pure markdown parsing; never burns tokens
- ❌ No auto-edits to your plans — read-only consumption
- ❌ No remote sync — git the data file if you want it synced

## Repo layout

```
claude-code-gamify/
├── README.md           ← you are here
├── LICENSE             ← MIT
├── install.sh          ← one-shot installer
├── skills/quest/       ← the skill (SKILL.md + 3 .py + themes/)
├── hooks/              ← quest-plan-autosync.sh
├── systemd/            ← quest-dashboard.service template
├── examples/           ← sample quests.json + config.json
└── docs/               ← theming, schema, adding-projects guides
```

## Contributing

Themes welcomed. PRs that add: new theme directory + landmarks + minimal docs in `themes/<name>/README.md`. Keep zero-dep philosophy — if it needs npm install, it's a different project.

## License

MIT — see `LICENSE`.
