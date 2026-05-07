# Claude Code Quest

> RPG-style project roadmap dashboard for Claude Code users — themed maps, auto-progress from plan checkboxes, multi-project tracking, zero dependencies.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Zero dependencies](https://img.shields.io/badge/deps-zero-brightgreen.svg)](#architecture-choices-and-what-we-said-no-to)

**Live demo URL** (after install): <http://localhost:8770>

---

## What is this?

A localhost dashboard that turns your Claude Code plans into a gamified visual roadmap. Each project becomes a themed map; each plan becomes a quest with status, tasks, branch, KPI, and "Why this matters." A small `/quest` skill manages the data; an async hook keeps it in sync with your `~/.claude/plans/*.md` files automatically — **without ever calling an LLM.**

You see all your projects at a glance, click into any quest, expand a deed to read its problem → solution. Filter by status, swap themes, drop in your own.

## Who is this for?

- **Solo devs juggling 3+ codebases** under one Claude Code install — you're losing track of what's blocked vs in-progress vs shipped, and you want a single visual.
- **Multi-project freelancers / consultants** who plan work via plan files and want a dashboard that updates itself when you check off boxes.
- **Anyone using Claude Code's plan mode** seriously — if you write `~/.claude/plans/*.md` files, this turns them into a navigable game world.

## How is this different from Linear / Notion / Trello / Jira?

| | Quest | Linear | Notion | Trello | Jira |
|---|---|---|---|---|---|
| Lives offline / localhost | ✅ | ❌ | ❌ | ❌ | ❌ |
| Reads plans you already write | ✅ | ❌ | ❌ | ❌ | ❌ |
| Zero LLM tokens / API cost | ✅ | n/a | n/a | n/a | n/a |
| Account / login required | ❌ | ✅ | ✅ | ✅ | ✅ |
| Themable (drop-in folders) | ✅ | ❌ | partial | ❌ | ❌ |
| Built for one person | ✅ | ❌ (team) | partial | partial | ❌ (team) |
| Setup time | <2 min | ~15 min | ~10 min | ~5 min | hours |
| Your data leaves your machine | ❌ | ✅ | ✅ | ✅ | ✅ |

It's not trying to compete with team-issue trackers. It's the personal layer above your codebases — the bird's-eye view you can't get from `git log` or your editor's tab bar.

## What's in the box

| Component | What |
|---|---|
| `/quest` skill | `status`, `add`, `update`, `done`, `theme`, `render`, `init` subcommands |
| Hand-rolled renderer | Zero-dep Python (~280 LOC). `{{var}}`, `{{#each}}`, `{{#if}}`, `{{> partial}}` |
| Two ready themes | Pokémon (cartoon, Fredoka) + Storybook (parchment, Eczar) — 3 views × 7 landmark SVGs each |
| Shared partials | `_back-link`, `_taskslist`, `_meta-row`, `_progress-bar`, `_pills`, `_why`, `_next-step` |
| Click-to-expand briefs | Each task and the next-step expand to show "Problem → Solution" sentences |
| Status filter bar | All / Active / Visited / Sealed (Pokémon) — All / Reading / Read / Sealed (Storybook), URL-bookmarkable |
| Auto-progress hook | PostToolUse async, parses `## Section 13` checkboxes into `tasks[]` + `progress` — **zero LLM calls** |
| Plan sub-bullet parser | `- [x] Title` followed by `- Problem: …` / `- Solution: …` becomes click-expandable detail |
| systemd unit | localhost:8770, hardened (`ProtectSystem=strict`), auto-starts on boot |

## Install

```bash
git clone https://github.com/ytrofr/claude-code-quest ~/claude-code-quest
cd ~/claude-code-quest
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
                                │    3. parse Problem:/Solution:     │
                                │       sub-bullets per checkbox     │
                                │    4. extract git branch + commit  │
                                │    5. update or add quest          │
                                │    6. trigger render               │
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
  quest-log.html.tmpl # listing view (with filter bar)
  plan-card.html.tmpl # per-quest detail (with click-expand briefs)
  landmarks/
    house.svg.tmpl   tower.svg.tmpl   mill.svg.tmpl
    bridge.svg.tmpl  camp.svg.tmpl    cave.svg.tmpl   castle.svg.tmpl
```

Shared partials (`themes/_shared/_*.html.tmpl`) cover cross-theme structure — themes provide CSS for the `qd-*` class hooks. See `skills/quest/themes/README.md` and `docs/theming.md`.

## Data schema (v2)

`quests.json` per-quest, all v2 fields optional:

| Field | Type | Source |
|---|---|---|
| `id`, `n`, `name`, `desc`, `landmark`, `status`, `progress`, `xp_reward`, `plan`, `next_step` | core | hand-set or `/quest` |
| `tasks[]` | `[{title, done, problem?, solution?}]` | auto-parsed from plan §13 checkboxes + sub-bullets |
| `last_touched` | ISO8601 | auto-set by autosync |
| `branch`, `last_commit{sha,msg,date}` | git | auto-pulled from local repo |
| `why`, `kpi` | string | hand-set |
| `next_step_problem`, `next_step_solution` | string | hand-set |
| `blockers[]`, `tags[]`, `depends_on[]`, `links[{project,quest}]` | arrays | hand-set |
| `effort{estimate_hr,actual_hr}` | object | hand-set |

See `examples/quests.json` for fully-populated samples (apollo, atlas, nova) and `docs/data-schema.md` for the full reference.

## Plan markdown — auto-progress shape

Write your plans normally. Sub-bullets under each checkbox become click-expandable briefs:

```markdown
## Section 13 — Post-Validation
- [x] Wire OAuth callback handler
  - Problem: Google deprecated the old endpoint; existing flow throws 400.
  - Solution: Migrate to /v3 endpoint + update redirect URI in console.
- [ ] Add session refresh middleware
  - Problem: Tokens expire mid-request, causing silent 401s.
  - Solution: Refresh proactively at 90% TTL with sliding window.
```

The hook parses checkbox state → `progress`, sub-bullets → `problem` / `solution` per task. Backward-compatible: plain checkboxes without sub-bullets render as non-clickable rows.

## Natural-language triggers (with Claude Code)

Once installed, an auto-loaded rule teaches Claude to recognize:

| You say | Claude runs |
|---|---|
| "what's the status of apollo?" | `/quest status` + cites the URL |
| "mark X done" | `/quest done <project> <id>` |
| "switch atlas to pokemon theme" | `/quest theme atlas pokemon` |
| Write a plan with `**Project**: <id>` BLUF | quest auto-appears, no command needed |

## FAQ

**Does this cost anything?** No. Everything runs on your machine. Zero LLM calls, zero API tokens, zero cloud services.

**Does my data leave my machine?** No. The systemd service binds to `127.0.0.1:8770`, the JSON lives in `~/.claude/quest/data/`, and the public engine repo only ships fictional example data (apollo, atlas, nova). Your real projects stay private.

**Do I need to run Claude Code for it to work?** No. Once installed, the dashboard runs as a systemd service. The auto-progress hook only fires inside Claude Code sessions, but you can run `/quest` commands manually anytime.

**Can I add my own theme?** Yes — drop a folder under `themes/<name>/` with a `theme.json`, three view templates, and seven landmark SVGs. The renderer auto-discovers it. See `docs/theming.md`.

**Does it work on Windows / macOS?** Linux + WSL fully supported (systemd unit included). macOS and Windows: the renderer + skill work fine, but you'll need to start the static server manually (`python3 -m http.server 8770 --directory ~/.claude/quest/site`) instead of via systemd. Or use `launchd` (macOS) or NSSM (Windows) — PRs welcome.

**What's the difference between Quest and Linear / Trello?** Linear and Trello are team issue trackers — they assume a server, accounts, multi-user collaboration. Quest is the personal birds-eye layer above your codebases — it reads plans you already write, runs offline, costs nothing. See the comparison table above.

**How do I add a new project?** Run `/quest init <id>`, edit `~/.claude/quest/config.json` to add the path mapping, optionally drop a `quest-link.md` pointer in the project's `.claude/` dir. See `docs/adding-projects.md`.

**Can the parser handle nested plans / Hebrew / non-English content?** Yes. UTF-8 throughout. The parser only looks for the `- [x]`/`- [ ]` checkbox pattern in `## Section 13`; it doesn't care what's between the brackets.

## Architecture choices (and what we said NO to)

- ✅ Zero-dep Python renderer — no jinja, no node, no build step
- ✅ Static HTML output — `python3 -m http.server` is enough; no Flask/FastAPI
- ✅ systemd-managed service — restart, logging, lifecycle handled
- ✅ Local-only dashboard — bound to 127.0.0.1; no external surface
- ✅ Vanilla JS for filter UI — no framework, ~25 lines, accessible (`role="tab"`, `aria-selected`)
- ❌ No tiered XP — flat 25 per quest, cosmetic only
- ❌ No LLM-driven progress — pure markdown parsing; never burns tokens
- ❌ No auto-edits to your plans — read-only consumption
- ❌ No remote sync — git the data file if you want it synced
- ❌ No JS framework / npm — keeping the install footprint near zero

## Repo layout

```
claude-code-quest/
├── README.md           ← you are here
├── LICENSE             ← MIT
├── CITATION.cff        ← academic citation metadata
├── install.sh          ← one-shot installer
├── skills/quest/       ← the skill (SKILL.md + 3 .py + themes/)
├── hooks/              ← quest-plan-autosync.sh
├── systemd/            ← quest-dashboard.service template
├── examples/           ← sample quests.json + config.json
├── docs/               ← theming, schema, adding-projects guides
└── .github/            ← issue templates
```

## Contributing

Themes welcomed. PRs that add: new theme directory + landmarks + minimal docs in `themes/<name>/README.md`. Keep zero-dep philosophy — if it needs npm install, it's a different project.

Bug? Open a [bug report](https://github.com/ytrofr/claude-code-quest/issues/new?template=bug_report.yml). Idea? File a [feature request](https://github.com/ytrofr/claude-code-quest/issues/new?template=feature_request.yml).

## License

MIT — see `LICENSE`.

---

<sub>Tags: claude-code, anthropic, project-management, roadmap, dashboard, rpg, gamification, developer-tools, productivity, todo-list, multi-project, kanban-alternative, zero-dependencies, self-hosted, localhost-app, solo-developer, personal-knowledge-management</sub>
