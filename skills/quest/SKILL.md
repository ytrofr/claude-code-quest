---
name: quest
description: "Manage RPG-style project roadmaps — central quests.json + themed HTML dashboard at http://localhost:8770. Use when adding/updating/completing a quest, switching a project's theme, or asking 'what's the status of my projects?'."
user-invocable: true
allowed-tools: "Bash, Read"
argument-hint: "<status|init|add|update|done|theme|render> [args]"
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
| `/quest update <project> <quest>` | Patch progress, next step, name, etc. |
| `/quest done <project> <quest>` | Mark done; awards XP; promotes next locked → current |
| `/quest theme <project> <theme>` | Swap theme (e.g. pokemon ↔ storybook) |
| `/quest render` | Regenerate all HTML |

After every mutating command, the renderer runs automatically.

## How to invoke

`/quest` dispatches to `python3 ~/.claude/skills/quest/quest.py <subcommand> ...`. From this skill, run via Bash:

```bash
python3 ~/.claude/skills/quest/quest.py status
python3 ~/.claude/skills/quest/quest.py init apollo
python3 ~/.claude/skills/quest/quest.py add apollo "Build login flow" --landmark tower --plan apollo-login.md --next "wire OAuth callback"
python3 ~/.claude/skills/quest/quest.py update apollo build-login --progress 0.8 --next "ship to staging"
python3 ~/.claude/skills/quest/quest.py done apollo build-login
python3 ~/.claude/skills/quest/quest.py theme apollo storybook
```

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
          "links": [],
          "effort": {"estimate_hr": 4, "actual_hr": 2}
        }
      ]
    }
  }
}
```

**Fields you'll touch via commands**: `name`, `desc`, `landmark`, `status` (done/current/locked), `progress` (0.0-1.0), `next_step`, `plan`, `theme`. Never hand-edit the JSON; use the commands.

## Theme system

- Themes live at `~/.claude/skills/quest/themes/<name>/`
- Each theme provides 3 templates (`route.html.tmpl`, `quest-log.html.tmpl`, `plan-card.html.tmpl`), 7 landmark SVGs (`landmarks/{house,tower,mill,bridge,camp,cave,castle}.svg.tmpl`), and a `theme.json`.
- Shared partials at `themes/_shared/` (`_back-link`, `_taskslist`, `_meta-row`, `_progress-bar`). Themes can override by placing same-named file in their dir.
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
