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
