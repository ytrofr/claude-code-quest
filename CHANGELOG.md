# Changelog

All notable user-facing changes. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · [Semantic Versioning](https://semver.org/).

## [1.6.1] — 2026-05-09

Plan-card readability + ergonomics polish.

### Added

- **`/quest update --problem` and `--solution`** flags. Authors plain-language Problem/Solution lines on a quest without hand-editing JSON. Encourages human-friendly summaries on the plan card even when the underlying plan's BLUF is dense engineering speak.
- **"Hide done" toggle** in the Claude Actions header. One-click filter that collapses every `[done]` action row in both the expanded list and the next-3 peek. State persists per-quest in localStorage (`qd-hide-done-<pid>-<qid>-cc`). Click stops propagation so it doesn't fight the section's collapse arrow.

### Changed

- **Font sizes normalized** across both themes. Removed 23 distinct fractional values (`12.1px`, `13.2px`, `14.3px`, `15.4px`, `16.5px`, `17.6px`, `19.8px`, `26.4px`, `28.6px`, `35.2px`, `39.6px`, `70.4px`, …) — all rounded to a clean integer scale: 10/11/12/13/14/15/16/18/19/20/21/22/24/26/28/30/32/36/64. Fixes type rhythm across plan-card, route, quest-log, and global-index in both pokemon and storybook themes.

## [1.6.0] — 2026-05-09

Major release: every plan-card now has the rich "Your Actions / Claude's Actions" coordination surface, the engine supports multiple active quests per project, and CC sessions get a clickable hyperlink to their current quest in the statusline.

### Added — Multi-active quests per project

- **`?q=<id>` URL dispatcher** on `plan-card.html` — every quest (current/locked/done) gets its own `<article class="qd-quest-block" data-quest-id="...">` block in a single static HTML file. JS reads `?q=` from the URL and toggles which block is visible; default = first current. Quest-log + storyline links now resolve to the correct block on a single page.
- **Active picker bar** above the plan-card body when ≥2 quests have `status: "current"`. Quick-switch links to each.
- **Home-index "Currently Battling" callout** shows `#N Name · +K more` when multiple actives.
- Quest-log already iterated all currents (no change needed) — visually highlights every active card.

### Added — Rich `### N. Title [STATUS]` action format

Replaces the legacy `[ ]` checkbox parsing for `## Section 13 — Post-Validation` and `## Section 14 — Your Actions`. Plans now author each item as a level-3 heading with status in brackets, body in inline markdown:

```markdown
### 1. Eyeball the live editor on production [TODO]
Open the [Ka'an WC URL](...) in your authed browser.
Hover any row → expect `[+ Col] [Layout ▾]` toolbar.
```

- 5 status colour buckets: `TODO` (yellow), `DONE` (green), `WAITING`/`BLOCKED` (gray), `QUEUED`/`AFTER 24H`/`ON GREENLIGHT` (blue), `CONTINUOUS`/`ONGOING` (teal). Free-form display text preserved verbatim; only the colour class is bucketed.
- **Inline markdown body**: `[label](url)` → `<a target=_blank>`, `` `code` `` → `<code>`, `**bold**` → `<strong>`, single newline → `<br>`, blank line → paragraph break.
- New shared partials: `themes/_shared/_actions-claude.html.tmpl` (renders §13 → "Claude's Actions"), `_actions-user.html.tmpl` (renders §14 → "Your Actions").
- **Synthesis fallback**: legacy plans with `[ ]` checkboxes auto-convert to actions at render time (TODO/DONE only, no body) so the rich UI applies to every quest. No plan rewrite required for the upgrade.

### Added — Theme SVG icon system

Every section-marker glyph on the dashboard now resolves through a partial: `{{> icons/<name>}}`. Themes can override per-icon by placing a same-named file at `themes/<theme>/icons/<name>.html.tmpl`; otherwise falls back to `_shared/icons/`. Built-in icon registry covers `user`, `robot`, `active`, `visited`, `sealed`, `branch`, `kpi`, `tags`, `plan-file`, `why`, `problem`, `solution`. Pokemon ships chunky friendly silhouettes (trainer cap, Magnemite-eye); storybook ships ornate brass/parchment (quill+inkwell, clockwork eye). Add a new icon by dropping any inline SVG file — no code changes needed.

### Added — Auto-extracted Links

`autosync.py` now extracts URLs from plan markdown into the quest's Links section. Two-tier strategy:

1. **Tier 1 (preferred)** — dedicated `## Links` / `## Useful links` / `## Relevant links` heading. Markdown `[label](url)` and bare URLs both supported.
2. **Tier 2 (fallback)** — when no Links heading exists, scans `## Section 13 — Post-Validation` and `## Section 0.1` for URLs.

Auto-extracted entries tagged `source: "autosync"`; manual `--add-link` entries (no `source` field, or `source: "manual"`) are preserved across autosync rewrites.

### Added — Collapsible sections + next-3 peek

All major plan-card sections (Claude's Actions, Your Actions, legacy Deeds, legacy To-Do) wrap in `<details data-qd-collapse="...">` collapsed by default. The collapsed `<summary>` shows a peek of the next 3 not-done items: numbered badge, title, status pill. Click to expand full numbered list. Open/closed state persisted per-quest in `localStorage[qd-collapse-<pid>-<quest-id>-<section>]`.

### Added — Empty-state placeholders

When a quest has Claude actions but no Your actions (or vice versa), the missing section renders as a dashed placeholder card with a "no items yet — add `## Section N` to your plan" hint. Discoverable, never silent.

### Added — Quest claim CLI + CC statusline integration

Sessions can bind themselves to a quest so the dashboard shows what's being worked on right now:

- `/quest claim <project> <quest-id> [--session-name X]` — bind THIS session to a quest. With no args, auto-detects from cwd's project + most-recently-touched current quest.
- `/quest unclaim` — release this session's claim, statusline reverts to auto-detect.
- `/quest claimed` — print the current claim or auto-detect fallback.

Session identity = `(claude_pid, /proc/<pid>/stat field-22 starttime ticks)` — deterministic per CC instance, no inter-agent bus dependency.

`claimed_session_name` field on a quest gets stamped at claim time. The plan-card `<h2>` title renders `Quest Name (session-name)` when the kebab-cased session name differs from the quest id; otherwise just the quest name (no duplicate).

A standalone helper script for the Claude Code statusline (`scripts/statusline-quest.sh` in the public repo) emits a clickable OSC-8 hyperlink: `quest: <project>/<quest-id> · <session-name>` linking to the plan-card URL. Modern terminals (Windows Terminal, iTerm2, kitty, recent VS Code, Ghostty) render the tag as a single-click link. `STATUSLINE_COMPACT=1` env var collapses everything onto one line for short terminals.

### Added — `paths_map` separator-aware matching

Auto-detect now matches a path_map prefix when cwd is exactly the prefix OR starts with `prefix` followed by a separator (`/`, `-`, `_`). One entry like `~/LimorAI` covers all sibling worktrees `LimorAI-Limor`, `LimorAI-staging`, etc. without overmatching `LimorAI2`. Resolved project is also validated against `quests.json` — aspirational path_map entries that don't have a corresponding dashboard project fall through to the dashboard root instead of emitting a 404 link.

### Changed

- Plan-card `<h2>` title uses `display_name` (falls back to `name` when no session is claimed).
- `_taskslist` and `_user-tasks` partials now render only when the legacy `tasks[]` / `tasks_user[]` exists AND no synthesised `actions[]` / `actions_user[]` is present — prevents duplicate sections during the legacy → rich-action transition.
- All emoji literals (⚔ ★ 🔒 👤 🤖 ⎇ 📊 🏷 ✦ 📜) replaced with theme SVG icon partials. Themes have full control over their visual identity; users can swap any icon by editing one SVG file.

### Internal

- New `HOISTED_QUEST_FIELDS` constant in `render.py` lists every field that should be visible at per-quest scope when rendering a plan-card block (so `_taskslist`, `_links`, etc. resolve correctly per quest).
- `_quest_scope(project, q)` helper builds the per-quest render scope without mutating the project dict — drops fields hoisted from the first-current quest, then re-hoists from this quest. Means each block's partials see only their own data.
- Partial resolver regex now allows `/` in partial names (`{{> icons/user}}`), enabling subdirectory layouts like `themes/<name>/icons/`.

## [1.5.0] — 2026-05-09

### Added
- **Quest links section on the plan card** — each quest can carry an array of `{url, label, desc}` entries rendered as a clickable Links section between Next Move and the meta-row. Use this for deploy URLs, dashboards, PR/issue links, monitoring panels, related plan files — anything someone resuming the quest needs one-click access to.
- **`/quest update --add-link "URL|LABEL|DESC"`** — repeatable flag to append link entries. LABEL and DESC are optional (URL alone uses URL as label).
- **`/quest update --clear-links`** — wipe link entries on a quest. Runs before any `--add-link` in the same invocation, so `--clear-links --add-link "..." --add-link "..."` is the idiomatic "replace" pattern.
- **Shared partial `themes/_shared/_links.html.tmpl`** — renders the section across all themes; iterates `{{#each links}}` and skips entirely when `links` is empty.
- **2-row layout** on each link card: bold label (left) + monospace URL (right-aligned) on row 1; full-width subtitle (desc) on row 2. Mobile (<720px) stacks into a single column with label → desc → URL ordering.

### Internal
- `render.py` already hoisted `active.links` into project scope (no change needed); the v1.5.0 work was renderer surface (partial + per-theme CSS) plus the CLI flags. Schema v2 unchanged — `links` field has been declared since v1.0 but was never rendered until now.
- Pokemon theme styles `.qd-link-anchor` with `#f7eed8` background, deep-red label (`#5a1818`), monospace dimmed URL. Storybook theme uses serif label, parchment background, dashed hover underline.

### Migration
No action required. Existing `quests.json` files render unchanged — quests with empty/missing `links` skip the section entirely. To start adding links to a quest:
```bash
/quest update <project> <quest> \
  --add-link "https://staging.example.com|Staging|Hit after deploy to verify" \
  --add-link "https://github.com/me/repo/pull/42|PR #42|Code review"
```

## [1.4.1] — 2026-05-08

### Fixed
- **Quest-label overflow on the route map** — labels under each quest landmark are now auto-sized to fit the quest name. Previously the rect was hardcoded to `width="100"` (pokemon) and the storybook trapezoid to `±52` half-width, so longer names like "The Adoption Watchtower" or "The Evolution Forge" overflowed their backgrounds. Width now derives from name length (`max(80, (chars+8) × 7 + 18)`) via new `label_width` / `label_x` / `label_half` / `label_half_inner` fields populated in `precompute()`.
- **Quests #8 and beyond rendered at (0,0)** — `theme.json::positions` only listed coords for quests 1–7. Projects with 8+ quests had every additional landmark stacked at the SVG origin (top-left, clipped). Pokemon and storybook themes now ship coords for #8 and #9; #6 / #7 nudged slightly so long-name labels stay within the 1200×540 viewBox.

### Internal
- `precompute()` per-quest section gains label-sizing math; templates reference `{{q.label_width}}` / `{{q.label_x}}` (pokemon rect) and `{{q.label_half}}` / `{{q.label_half_inner}}` (storybook trapezoid) instead of hardcoded values. Backward-compatible — anyone embedding the templates in their own theme should pick up the auto-sizing for free after this release.

## [1.4.0] — 2026-05-08

### Added — Home index
- **Trainer Hall home index** — `/` now renders a Pokémon-themed card grid (one card per project) instead of a bullet list. Each card shows level pill, sky-and-grass hero strip with inline-SVG landmark icon, gold XP bar, three stat pills (Active / Visited / Sealed), "Currently Battling" callout, and **Begin Adventure** + **Pokédex** buttons. Header crown bar shows aggregate **Levels / Total XP / Routes Cleared / Active Battles** summed across every project.
- **`/quest style <project>` subcommand** — set per-project home-index card accent color (`--accent #ff6a3a`) and landmark icon (`--icon house|tower|mill|bridge|camp|cave|castle`). Empty string clears back to the per-pid default.
- **Schema v2 fields** (both optional): `accent` (6-digit hex) and `icon` (landmark name). Backward-compatible — `quests.json` files without these fields render identically using rotating defaults baked into `render.py`.

### Added — Storyline + filters
- **Storyline rendering on plan-card** — meta box surfaces **Sequel to** ◀ (predecessors from `depends_on`), **Leads to** ▶ (auto-computed successors via reverse-lookup), and **Plans** (originating plan + optional `plans` array of sub-plans). Quest names render as clickable links.
- **Multi-select status filter on quest-log** — Active / Visited / Sealed pills toggle independently (replaces the prior exclusive single-select). Off-state pills go dashed-and-muted. Plus **Show All** and **Active Only** quick-action buttons. State persists per-project in `localStorage`.
- **Hide-done deeds toggle on plan-card** — toggle in the Deeds header hides ticked sub-tasks while keeping todos visible. Same `localStorage` key as the status filter so one user preference covers both views.

### Added — Plan + lifecycle workflow
- **Lean descriptions** — auto-derived ≤140-char `desc`, with **Problem** / **Solution** / **Why** lifted from a plan's BLUF block.
- **`/quest reset --chapter <name>`** — close out a chapter and start a fresh map. **Preview-by-default; `--yes` required to actually mutate** (prevents accidental NL-triggered resets). Locked quests survive into the new chapter by default; pass `--clean` to wipe them too. Past chapters surface as "📜 Past chapters" badges under the route map.
- **`/quest chapters [<project>]`** — list archived chapters across one or all projects.
- **`depends_on` chain rendering** — sequential dependencies between quests. Autosync logs a hint when a new plan mentions an existing quest by id.
- **`/document` Phase 3 autosync** — running `/document` on a plan-shaped artifact now fires `autosync.py` automatically.

### Changed
- `render_global_index()` rewritten to use the shared template engine — replaces the prior 30-line inline-string bullet list. Template lives at `skills/quest/themes/_shared/global-index.html.tmpl`.
- `render.py` grew to ~430 LOC with the new `precompute_global_index()`, `lighten()` helper, and `DEFAULT_ACCENTS` / `DEFAULT_ICONS` / `ACCENT_PALETTE` / `ICON_ROTATION` constants.
- `/quest` skill argument hint now includes `style`, `reset`, `chapters` alongside the originals.

### Fixed
- **Nested-anchor card collapse** — the prior `/index.html` and the early Trainer Hall mock both nested `<a>` inside `<a>` (secondary "Pokédex" link inside outer card link). HTML auto-closes the outer anchor mid-DOM, silently breaking layout — cards 2-3 collapsed to wrong sizes. Fix: outer is `<div class="card">`, primary `<a>` covers the card via `::after { position: absolute; inset: 0; z-index: 1 }`, secondary `<a>` lives on `position: relative; z-index: 2`.
- **BLUF parser** — tolerates markdown blockquote prefix (`> **Project**:`), `[\s>*\-]*` char class.

### Migration
No action required. Existing `quests.json` files render unchanged. To customize a project's card look:
```bash
/quest style limor --accent "#ff6a3a" --icon house
/quest style smith --accent ""        # clear back to default
```

## [1.2.0] — 2026-05-07

Initial public release of the engine. See [v1.2.0 release notes](https://github.com/ytrofr/claude-code-quest/releases/tag/v1.2.0) for the full snapshot: pokemon + storybook themes, autosync hook, systemd unit, MIT license, SEO/AEO/GEO README, CITATION.cff, ISSUE_TEMPLATE.

[1.5.0]: https://github.com/ytrofr/claude-code-quest/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/ytrofr/claude-code-quest/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/ytrofr/claude-code-quest/compare/v1.2.0...v1.4.0
[1.2.0]: https://github.com/ytrofr/claude-code-quest/releases/tag/v1.2.0
