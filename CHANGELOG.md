# Changelog

All notable user-facing changes. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · [Semantic Versioning](https://semver.org/).

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

[1.4.0]: https://github.com/ytrofr/claude-code-quest/compare/v1.2.0...v1.4.0
[1.2.0]: https://github.com/ytrofr/claude-code-quest/releases/tag/v1.2.0
