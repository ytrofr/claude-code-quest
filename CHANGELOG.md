# Changelog

All notable user-facing changes. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · [Semantic Versioning](https://semver.org/).

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
