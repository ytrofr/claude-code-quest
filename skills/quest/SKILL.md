---
name: quest
description: "Manage RPG-style project roadmaps — central quests.json + themed HTML dashboard at http://localhost:8770. Use when adding/updating/completing a quest, switching a project's theme, or asking 'what's the status of my projects?'."
user-invocable: true
allowed-tools: "Bash, Read"
argument-hint: "<status|init|add|update|done|theme|style|render|reset|chapters> [args]"
---

# /quest — RPG-style project roadmap

Visualize your projects as gamified RPG maps. Each project gets a themed dashboard view: an overworld map, a quest log, and a per-quest plan card.

**Single source of truth**: `~/.claude/quest/data/quests.json`. Two built-in themes: **pokemon** (top-down regional map) and **storybook** (illuminated parchment). Renderer outputs HTML at `~/.claude/quest/site/<project>/{route,quest-log,plan-card}.html`. Localhost service at **http://localhost:8770** serves the dashboard and auto-starts on boot.

## Quick reference

| Command | What it does |
|---|---|
| `/quest status` | Print all projects, dashboard URL, theme list |
| `/quest init <project>` | Create new project entry |
| `/quest add <project> "<name>"` | Append a quest |
| `/quest update <project> <quest>` | Patch progress, next step, name, links, etc. |
| `/quest done <project> <quest>` | Mark done; awards XP; promotes next locked → current |
| `/quest theme <project> <theme>` | Swap theme (e.g. pokemon ↔ storybook) |
| `/quest style <project> --accent <#hex> --icon <name>` | Set the home-index card accent color and landmark icon (per-project override) |
| `/quest render` | Regenerate all HTML |
| `/quest reset <project> --chapter <name>` | **Preview only by default.** Pass `--yes`/`-y` to actually archive. `--clean` archives locked too. |
| `/quest chapters [<project>]` | List archived chapters (one or all projects) |

After every mutating command, the renderer runs automatically.

## How to invoke

`/quest` dispatches to `python3 ~/.claude/skills/quest/quest.py <subcommand> ...`. From this skill, run via Bash:

```bash
python3 ~/.claude/skills/quest/quest.py status
python3 ~/.claude/skills/quest/quest.py init apollo
python3 ~/.claude/skills/quest/quest.py add apollo "Build login flow" --landmark tower --plan apollo-login.md --next "wire OAuth callback"
python3 ~/.claude/skills/quest/quest.py update apollo build-login --progress 0.8 --next "ship to staging"
python3 ~/.claude/skills/quest/quest.py update apollo build-login \
  --add-link "https://staging.example.com/login|Staging login|Hit this after deploy to verify" \
  --add-link "https://github.com/me/apollo/pull/42|PR #42|Auth flow changes"
python3 ~/.claude/skills/quest/quest.py update apollo build-login --clear-links
python3 ~/.claude/skills/quest/quest.py done apollo build-login
python3 ~/.claude/skills/quest/quest.py theme apollo storybook
python3 ~/.claude/skills/quest/quest.py style apollo --accent "#3aaa6a" --icon castle
python3 ~/.claude/skills/quest/quest.py reset apollo --chapter "phase-1-launch"
python3 ~/.claude/skills/quest/quest.py chapters apollo
```

## Chapters (map reset)

When a project finishes a major phase and you want a fresh roadmap, run `/quest reset <project> --chapter <name>`. **By default, this PREVIEWS only and exits — pass `--yes` (or `-y`) to actually mutate.** This prevents an ambiguous "we wrapped that up" remark from accidentally nuking 14 quests.

Preview output:
```
PREVIEW (no changes made — pass --yes to commit):
  project: limor
  chapter: 'phase-1-anchor'
  archive (5):
    [done   ] # 1 Anchor Town
    [current] # 2 Bundle B Code Pass
    ...
  survive (7):
    [locked ] # 3 Auditor V2 Hardening
    ...
  level/xp reset to baseline · 'Auditor V2 Hardening' will be promoted to current

To commit: rerun with --yes
```

Done + current quests are archived into `chapters[<name>]` (frozen, with `archived_at` timestamp). Locked quests survive into the new map by default — first locked auto-promotes to current. Pass `--clean` to wipe locked too. Level/xp reset to baseline.

Past chapters appear as a "📜 Past chapters: <name> (N)" badge under the route map. Chapters are append-only — re-using the same `--chapter <name>` appends to the existing list.

## Home Index (Trainer Hall)

The dashboard root at <http://localhost:8770/> renders a **Trainer Hall** — one Pokémon-style card per project, in a responsive grid. Each card shows: numbered badge, level pill, theme stamp, sky-and-grass hero strip with a landmark icon, project name + subtitle, gold XP bar, three stat pills (Active / Visited / Sealed), a "Currently Battling" callout for the active quest, and **Begin Adventure** + **Pokédex** buttons.

The hero strip color and landmark icon are per-project — drawn from optional `accent` and `icon` fields on the project (set via `/quest style`). Defaults exist for the six built-in projects; new projects rotate through a built-in palette + icon list until you call `/quest style` to lock them in.

```bash
# pick the look for a new project
python3 ~/.claude/skills/quest/quest.py style apollo --accent "#3aaa6a" --icon castle

# clear back to defaults
python3 ~/.claude/skills/quest/quest.py style apollo --accent "" --icon ""
```

The header crown bar shows aggregate **Levels / Total XP / Routes Cleared / Active Battles** summed across every project.

Implementation: template at `~/.claude/skills/quest/themes/_shared/global-index.html.tmpl`; scope built by `precompute_global_index()` in `render.py`. No partials — pure top-level template.

## Quest links — useful URLs on the plan card

Each quest can carry an array of links rendered as a **Links section** on the plan card. Each entry is `{url, label, desc}`. Use this for: deploy URLs, dashboard URLs, PR/issue links, monitoring panels, related plan files — anything someone resuming the quest needs one-click access to.

**Add links** via repeatable `--add-link "URL|LABEL|DESC"`:

```bash
python3 ~/.claude/skills/quest/quest.py update <project> <quest> \
  --add-link "https://localhost:8080/digest|Live digest|The actual feature" \
  --add-link "https://github.com/me/repo/pull/42|PR #42|Code review"
```

Format: `URL|LABEL|DESC`. Pipes split into 3 fields; LABEL and DESC are optional (URL alone uses URL as label).

**Clear before re-adding** (avoids accumulating stale entries):

```bash
python3 ~/.claude/skills/quest/quest.py update <project> <quest> --clear-links \
  --add-link "..." --add-link "..."
```

`--clear-links` runs first, then `--add-link` entries replace what was there.

**The routine — when to add links**:
- After shipping a feature: deploy URL, dashboard, KPI endpoint
- After opening a PR: PR URL + linked issue
- When parking a quest mid-flight: status URL, last good build, related Slack thread
- Any quest with a "go look at X" verification step — make X a one-click link
- Cross-references: related quests, related plan files, parent epic

Links render via the shared partial `themes/_shared/_links.html.tmpl`; each theme styles them in its own plan-card.html.tmpl. Layout: label · desc · monospace URL (right-aligned on wide screens, stacked on mobile).

### Auto-extraction from plan files

`autosync.py` extracts URLs from plan markdown automatically — you typically don't need `--add-link` if your plan is well-formatted. Two-tier strategy:

1. **Tier 1 (preferred)** — dedicated heading: `## Links` / `## Useful links` / `## Relevant links` / `## See also`. Autosync scans only that section. Format: `- [Label](https://url) — optional description` or bare `https://url` lines. Authors who fill this in get full control over what shows up.
2. **Tier 2 (fallback)** — when no Links heading exists, autosync scans `## Section 13 — Post-Validation` and `## Section 0.1` for markdown links + bare URLs. These sections commonly carry dashboard/health/deploy URLs.

Auto-extracted links are tagged `source: "autosync"` in `quests.json`. Manual `--add-link` entries (no `source` field, or `source: "manual"`) **survive autosync rewrites** — both coexist on the plan-card. Dedupe by URL (manual wins).

To force a fresh full extract: `--clear-links` removes manual + auto entries; next autosync repopulates from the plan.

## Plan-card sections — Your Actions / Claude's Actions

Plan-card renders TWO flat numbered sections per quest, marked with theme SVG icons (no emojis):

| Section | Source | Icon (pokemon / storybook) | When to use |
|---|---|---|---|
| **Your Actions** | `## Section 14 — Your Actions` | trainer cap / quill+inkwell | Things only the human can do — verify in browser, approve PR, hit a dashboard, pick the next track, leave a deploy alone for soak |
| **Claude's Actions** | `## Section 13 — Post-Validation` | Magnemite-style hovering eye / clockwork eye | Things Claude/the implementation is doing or queued to do — tests, deploys, code changes, undraft PR after soak |

Rendered flat (no collapse — all items always visible). Each item has a numbered badge, title with status pill, and a free-form HTML body (links, code, bold, line breaks).

### Authoring syntax — `### N. Title [STATUS]`

Each action is a level-3 heading under §13 or §14. Number prefix optional (auto-numbered if omitted). Status keyword in `[BRACKETS]` at end of line. Body is everything until the next `###` or `##` heading — supports inline markdown:

```markdown
## Section 14 — Your Actions

### 1. Eyeball the live editor on production [TODO]
Open the [Ka'an WC URL](https://example.com/wc) in your authed browser.
Hover any row → expect `[+ Col] [Layout ▾]` toolbar. Click `+ Col` → expect instant column.

### 2. Verdict — approve or list issues [TODO]
Tell Claude **"looks good"** OR paste any UX issues you spotted.

### 3. 24h soak window — leave deploy alone [WAITING]
Kill switch `LAYOUT_HTTP_CLONE_GUARD_ENABLED=true` is armed.

## Section 13 — Post-Validation

### 1. Wait for your eyeball verdict [WAITING]
No code changes pending until you greenlight. Parked in safe state.

### 2. Undraft `dev-websites → dev` PR [AFTER 24H]
Bundles `e136ab5` + `c8533d9`. Conditional on: 24h soak clean + your greenlight.

### 3. Update this card on each transition [CONTINUOUS]
TODO → DONE as items close.
```

### Status keywords + colour buckets

| Keyword (case-insensitive, free-form) | CSS class | Colour |
|---|---|---|
| `TODO` | `todo` | yellow |
| `DONE`, `COMPLETE`, `COMPLETED` | `done` | green (item title strikethrough + green num badge) |
| `WAITING`, `BLOCKED` | `waiting` | gray |
| `QUEUED`, `AFTER ...`, `ON ...` (e.g. `AFTER 24H`, `ON GREENLIGHT`) | `queued` | blue |
| `CONTINUOUS`, `ONGOING` | `continuous` | teal |
| Anything else | `default` | neutral |

Display text preserved verbatim — `[AFTER 24H]` shows as "AFTER 24H". Only the colour class is bucketed.

### Inline markdown supported in body

`[label](https://url)` → external link · `` `code` `` → inline code · `**bold**` → strong · `*italic*` → em · single newline → `<br>` · blank line → paragraph break. Anything else is HTML-escaped.

### Legacy `## Section 13/14` checkbox plans

Plans that pre-date this format (using `- [ ]` checkboxes under §13/§14) still parse correctly via fallback — autosync stores them in `tasks[]` / `tasks_user[]` and renders the older collapsible UI. To migrate: delete the checkboxes, replace with `### N. Title [STATUS]` + body. The next autosync swaps the old fields for the new `actions[]` arrays.

## Icon system — modular UI components

Every section-marker glyph on the dashboard resolves through a partial: `{{> icons/<name>}}`. Themes can override per-icon by placing their own version at `themes/<theme>/icons/<name>.html.tmpl`; missing overrides fall back to `themes/_shared/icons/<name>.html.tmpl`. Icons use inline SVG; default styles use `currentColor` so CSS can recolour them.

Built-in icon registry:

| Name | Used for | Pokemon look | Storybook look |
|---|---|---|---|
| `user` | Your Actions section header | Trainer cap with pokeball | Quill + inkwell |
| `robot` | Claude's Actions section header | Magnemite-style hovering eye | Clockwork brass eye |
| `active` | "Active" status, home-index crest, currently-battling marker | Crossed swords | Wax seal with heraldic mark |
| `visited` | "Visited" filter button | 5-point star | Illuminated 8-point star |
| `sealed` | "Sealed" filter button | Padlock | Brass key + lock plate |
| `branch` | Pill — git branch | shared default fork | shared default fork |
| `kpi` | Pill — KPI target | shared default bar chart | shared default bar chart |
| `tags` | Pill — quest tags | shared default tag | shared default tag |
| `plan-file` | "Plan file" / "Charter" footer | shared default scroll | shared default scroll |
| `why` | Marker on the "why" motivation line | shared default 8-point spark | shared default 8-point spark |

To add a new icon: drop `themes/_shared/icons/<name>.html.tmpl` (any inline SVG). Reference as `{{> icons/<name>}}`. To override per theme: create `themes/<theme>/icons/<name>.html.tmpl`. To swap an icon's design: edit the SVG file — next render picks it up, no code changes.

## Statusline integration — clickable quest link per session

Every CC session can show a clickable link to its current quest's plan-card in the statusline. Resolution is **hybrid**: an explicit `/quest claim` always wins; otherwise the statusline auto-detects from cwd + most-recently-touched current quest. Falls back to the project home, then the dashboard root.

### Claim commands

```bash
/quest claim <project> <quest-id>   # bind THIS session to a specific quest
/quest claim                        # bind to whatever auto-detect would pick (locks it in)
/quest unclaim                      # remove this session's claim — revert to auto-detect
/quest claimed                      # show what THIS session is currently claiming
```

Each session is identified by its `claude` process pid + raw `/proc/<pid>/stat` field-22 starttime ticks (deterministic per CC instance, survives subprocess churn). Claim file lives at `~/.claude/quest/run/session-<claude_pid>-<ticks>.quest` — single line: `<project>/<quest-id>`.

### Statusline display

Output format (last field): `quest:<short-tag>`. The tag is wrapped in an [OSC-8 hyperlink escape](https://gist.github.com/egmontkob/eb114294efbcd5adb1944c9f3cb5feda) so modern terminals (Windows Terminal, iTerm2, kitty, recent VS Code terminal) render it as a clickable link to the full plan-card URL. Clicking jumps straight to the dashboard at `http://localhost:8770/<project>/plan-card.html?q=<quest-id>`.

Tag shortening — long quest ids truncate at 22 chars with `…`:

| Tag | URL it opens |
|---|---|
| `quest:ogas/layout-editor-entry-…` | `http://localhost:8770/ogas/plan-card.html?q=layout-editor-entry-435-soak-ship` |
| `quest:ogas/-` (no current quest) | `http://localhost:8770/ogas/` |
| `quest:-` (no project from cwd) | `http://localhost:8770/` |

### Recommended SessionEnd hook (auto-unclaim)

Add to `~/.claude/settings.json` if you want claims to clear automatically when a session ends:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/skills/quest/quest.py unclaim 2>/dev/null || true" }
        ]
      }
    ]
  }
}
```

Without this, stale claim files accumulate at `~/.claude/quest/run/session-*.quest` — harmless (each is read only by the matching live session) but accumulates. Periodic prune: `find ~/.claude/quest/run -name 'session-*.quest' -mtime +7 -delete`.

### Bare terminal (no OSC-8 support)

If your terminal renders `\e]8;;…` literally instead of as a link, set `QUEST_STATUSLINE_NO_OSC8=1` in `~/.bashrc` — the statusline drops the escape wrapping and emits just the plain tag.

### Short terminals — single-line compact mode

If your terminal is short (less than ~30 visual rows), CC's bottom-bar may squeeze the second statusline line off-screen and you'll only see line 1. Two fixes:

**Easy fix: resize the terminal taller** (and slightly wider). CC needs ~3-4 free rows below the prompt for the dividers, statusline, permissions banner, and token count.

**Alternative — single-line compact mode**: set `STATUSLINE_COMPACT=1` in your shell environment. The statusline collapses everything onto one line; the plaintext URL trailer is stripped (the quest tag remains clickable via OSC-8 on supported terminals).

```bash
# Per-session:
STATUSLINE_COMPACT=1 claude --name my-quest

# Permanent in ~/.bashrc:
export STATUSLINE_COMPACT=1
```

Output comparison:

```
# Default (2-line — requires ~30+ row terminal):
AgentSmith | Opus 4.7 | 5h:71%→14:00 7d:44% | bus:smith:s3●→s1
quest: smith/whatsapp-auth-split · audit-gap-closure  →  http://localhost:8770/...

# Compact (1-line — fits any terminal):
AgentSmith | Opus 4.7 | 5h:71%→14:00 7d:44% | bus:smith:s3●→s1 | quest: smith/whatsapp-auth-split · audit-gap-closure
```

### Files involved

| File | Purpose |
|---|---|
| `~/.claude/scripts/statusline-quest.sh` | Bash helper — `quest_indicator <cwd>` function |
| `~/.claude/scripts/statusline.sh` | Sources helper, appends `quest:<tag>` field |
| `~/.claude/skills/quest/quest.py` | `cmd_claim`, `cmd_unclaim`, `cmd_claimed` |
| `~/.claude/quest/run/session-*.quest` | Per-session claim files (gitignored) |

## Multiple active quests per project

A project can have **any number of quests with `status: "current"`** simultaneously. Renderer:

- **Quest-log** highlights every current quest with the `card.current` class.
- **Home-index** card shows `#N Name · +K more` when 2+ are active.
- **Plan-card** emits one `<article class="qd-quest-block" data-quest-id="<id>">` per quest in the project (current + locked + done, all in one HTML file). A small JS dispatcher reads `?q=<id>` from the URL and toggles visibility — defaulting to first current. So `plan-card.html?q=<id>` resolves to the correct quest for any id.
- When 2+ currents exist, an **active-picker bar** appears at the top of plan-card listing all currents as quick-switch links.

To run multiple plans in parallel, just create them — autosync sets the second new plan to `status: locked` by default. Manually flip it with `/quest update <project> <quest> --status current` (or `/quest done <previous>` then `/quest add` works too).

## Sequential dependencies

Add `depends_on: [quest-id-1, quest-id-2]` to a quest in JSON (or write `> **Depends on**: id1, id2` in a plan's BLUF block — autosync will pick it up). The renderer surfaces this in two places:

- **Quest log** (locked card): "After: #N Quest Name" hint below the lock row
- **Plan card** (active quest): "Sequel to:" row in the meta block

A quest's `depends_on_str` resolves ids to "#N name" format automatically. Unresolved ids (deleted quest) display raw.

**Auto-suggested**: when autosync adds a NEW quest whose plan body mentions an existing quest by id (e.g. `` `build-foo` ``) or full name AND the BLUF lacks `**Depends on**:`, autosync logs a hint to `~/.claude/quest/logs/autosync.log`:
```
HINT limor/new-quest: plan mentions existing quest(s) ['build-foo'] —
add `> **Depends on**: build-foo` to BLUF if sequential
```
Hint only — never auto-writes. Apply by editing the plan's BLUF and triggering another autosync run.

## Auto-progress (no token cost)

`autosync.py` runs on every plan write (PostToolUse async, ~30ms). It scans plan markdown for `## Section 13 — Post-Validation` checkboxes (or all checkboxes as fallback) and updates the matching quest's `tasks[]` + `progress`. It also picks up `branch` + `last_commit` from local git. **Pure local Python — never calls an LLM.**

If a plan file is new (no matching quest exists), autosync ADDS a quest. If it matches an existing quest, autosync UPDATES progress + tasks.

## Data shape (v2 — all v2 fields optional)

```json
{
  "version": 2,
  "projects": {
    "apollo": {
      "name": "Apollo",
      "subtitle": "User-facing dashboard",
      "theme": "pokemon",
      "accent": "#3aaa6a",
      "icon": "castle",
      "level": 2,
      "xp": {"current": 50, "max": 100},
      "quests": [
        {
          "id": "build-login", "n": 1, "name": "Login Tower",
          "desc": "OAuth flow with email + Google",
          "landmark": "tower", "status": "current",
          "progress": 0.6, "xp_reward": 25,
          "plan": "apollo-login.md", "next_step": "Wire OAuth callback",

          "tasks": [
            {"title": "Pick OAuth library", "done": true},
            {"title": "Wire callback handler", "done": false}
          ],
          "last_touched": "2026-05-07T14:23:00Z",
          "branch": "feat/login",
          "last_commit": {"sha": "abc1234", "msg": "wip: oauth", "date": "2026-05-07T..."},
          "why": "Login is the gate to everything else; ship it first.",
          "blockers": [],
          "tags": ["auth", "core"],
          "kpi": "login success rate >99%",
          "depends_on": [],
          "links": [
            {"url": "https://example.com", "label": "Display name", "desc": "Optional one-line description"}
          ],
          "effort": {"estimate_hr": 4, "actual_hr": 2}
        }
      ]
    }
  }
}
```

**Fields you'll touch via commands**: `name`, `desc`, `landmark`, `status` (done/current/locked), `progress` (0.0-1.0), `next_step`, `plan`, `theme`, `accent`, `icon`, `links` (via `--add-link` / `--clear-links`). Never hand-edit the JSON; use the commands.

**Project-level home-index fields** (both optional, both have defaults):
- `accent` — 6-digit hex (e.g. `#ff6a3a`) used for the hero strip foreground hill, the lightened sky tint, and the colored progress accents on the home-index card. Per-pid defaults in `render.py::DEFAULT_ACCENTS`. Override via `/quest style <project> --accent <#hex>`.
- `icon` — landmark name from the project's theme (`house`, `tower`, `mill`, `bridge`, `camp`, `cave`, `castle`). Drawn inside the hero strip. Per-pid defaults in `render.py::DEFAULT_ICONS`. Override via `/quest style <project> --icon <name>`.

## Theme system

- Themes live at `~/.claude/skills/quest/themes/<name>/`
- Each theme provides 3 templates (`route.html.tmpl`, `quest-log.html.tmpl`, `plan-card.html.tmpl`), 7 landmark SVGs (`landmarks/{house,tower,mill,bridge,camp,cave,castle}.svg.tmpl`), and a `theme.json`.
- Shared partials at `themes/_shared/` (`_back-link`, `_taskslist`, `_meta-row`, `_progress-bar`, `_links`). Themes can override by placing same-named file in their dir.
- To add a new theme: drop a folder, no code changes. See `themes/README.md`.

## Configuration (project path map)

`~/.claude/quest/config.json` maps absolute paths to project ids — used by the autosync hook to figure out which project a plan write belongs to. User-owned, NOT versioned in the public engine repo. Example:

```json
{"path_map": [{"path": "/home/me/myproject", "id": "myproject"}]}
```

## Troubleshooting

| Symptom | First check |
|---|---|
| Quest didn't appear after plan write | `tail -50 ~/.claude/quest/logs/autosync.log` |
| Dashboard URL doesn't load | `systemctl --user status quest-dashboard` |
| HTML looks wrong / partial missing | `python3 ~/.claude/skills/quest/render.py --dry-run` |
| Wrong project chosen by hook | autosync log includes resolution trace; check `~/.claude/quest/config.json` |
| Theme not picking up | `python3 ~/.claude/skills/quest/quest.py status` lists discovered themes |

## Source of truth

- Skill: `~/.claude/skills/quest/`
- Data: `~/.claude/quest/data/quests.json` (versioned)
- Config: `~/.claude/quest/config.json` (path map; NOT versioned in public engine)
- Site: `~/.claude/quest/site/` (gitignored, regeneratable)
- Logs: `~/.claude/quest/logs/` (gitignored)
- Hook: `~/.claude/hooks/quest-plan-autosync.sh`
