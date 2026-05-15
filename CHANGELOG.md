# Changelog

All notable user-facing changes. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · [Semantic Versioning](https://semver.org/).

## [1.10.0] — 2026-05-15

Prompt-driven quest claim auto-rebind, tag editing on the plan-card detail page, inline markdown in the My To-Do list, WSL2-aware editor deeplinks.

### Added

- **Prompt-rebind hook** — new `hooks/quest-prompt-rebind.sh` registered on `UserPromptSubmit`. Reads the user's prompt + the last assistant message from the active session's transcript, scores against the project's `status="current"` quests with an IDF tokenizer, and atomically rewrites the session's claim file when the signal is strong. Two-stage decision (user-alone first, joined-context fallthrough, conflict guard), ~110-150ms typical latency, fire-and-forget. Companion `skills/quest/prompt_rebind_scorer.py` (the worker) and `skills/quest/test_prompt_rebind.py` (28-test regression suite).
- **Three kill switches** for the rebind hook:
  - **Per-session lock**: `quest claim --lock <proj> <qid>` writes a `.lock` sidecar next to the claim file. The hook honors it and logs `acted=locked-skip`. Clear with `quest unlock`.
  - **Global dry-run**: `touch ~/.claude/quest/dry-run` — hook still scores and logs but never writes the claim file. Useful for tuning thresholds before activating.
  - **Hard disable**: `touch ~/.claude/quest/prompt-rebind-disabled` — hook exits at the bash entry point with no scorer invocation.
- **`quest unlock`** subcommand — removes the per-session lock sidecar without touching the claim itself.
- **`quest rebind-stats [--days N]`** subcommand — summarizes recent hook activity from `~/.claude/quest/log/rebind.jsonl`: action distribution, "acted" distribution (rebound / locked-skip / rebound-dryrun / etc), threshold-tune candidates (rebinds with thin margin OR suggests near rebind threshold), and this session's actual rebinds with from→to provenance.
- **`quest claim --lock`** flag — claim AND lock in one operation.
- **Tag editing on the plan-card detail page.** The chip row (existing on the Quest Log) is now also on `plan-card.html?q=<qid>` — same `+ tag` button, `× to remove`, and `💬 + session` binding. Chips also link to `quest-log.html?q=<tag>` for filtered views.
- **Inline markdown in My To-Do.** Task titles and notes now render `**bold**`, `*italic*`, and `` `inline code` ``. Hebrew + RTL text inside backticks preserved. Implementation: `sidecar.render_inline_md(text)`, applied per-line; templates use `{{{q.title_html}}}` for raw injection.

### Changed

- **Editor deeplink is now WSL2-aware.** On WSL2 (detected via `WSL_DISTRO_NAME`), the `✎ Edit in editor` link emits `vscode://vscode-remote/wsl+<distro><abs-path>` instead of `vscode://file/<abs-path>`. Native Linux / macOS still get the standard `vscode://file/` form. Fixes "path does not exist" when VS Code on Windows side handled a WSL absolute path.
- **`<article class="qd-quest-block">` wrapper** in the plan-card render now carries `data-project-id` and `data-quest-tags` so the chip-edit JS can POST correctly.
- **`.qd-task-title` styling** — explicit `font-size: 13px`, `line-height: 1.45`, `word-break: break-word`, and styled `<strong>` / `<em>` / `<code>` children. Fixes oversized prose-heavy task titles that broke the section layout.

### Internal

- New `prompt_rebind_scorer.py` module with bounded-I/O transcript tail-read (last 200KB, last 50 lines), IDF builder, two-stage `decide_action()`, and `run_from_stdin()` entry point. Soft-fails on every error path (missing transcript, no current quests, malformed JSON lines, /proc walk failure).
- AppendOnly `~/.claude/quest/log/rebind.jsonl` observability log.

## [1.9.0] — 2026-05-15

Freeform `tags[]` per quest, in-page search, session ribbon on the card image, "Open in editor" deeplink for My To-Do sidecars, and a small JSON API replacing the bare static server.

### Added

- **Freeform tags per quest.** New optional `tags[]` field on every quest in `quests.json`. Manage from three surfaces:
  - **UI chip row** under each quest card. `+ tag` opens an inline input (accepts comma-separated values). `×` on any chip removes. Click a chip body to filter the list by that tag.
  - **`💬 + session` button.** Cleaner entry for binding a quest to a chat conversation — type just the conversation name, the prefix `session:` is added automatically. Page reloads so the new `.illus` ribbon appears.
  - **CLI**: `quest tag <project> <quest> add foo,bar`, `quest tag … remove foo`, `quest tag … list`, `quest bind <project> <quest> [--session-name X]`, `quest unbind`, `quest mine`.
- **Session ribbon on the quest card.** Tags starting with `session:` render as a prominent dark pill (💬-prefixed) inside the `.illus` SVG below the status badge, with a soft red pulse on `current` quests — designed so "what's THIS chat working on" is visible at a glance. Multiple session tags stack vertically.
- **Live search bar.** Always-visible search at the top of every Quest Log page. Filters cards by name / desc / tags / id / status simultaneously. Debounced; persists in `?q=` for shareable URLs. `Esc` or `✕` clears.
- **`✎ Edit in editor` link on every My To-Do block** — emits a `vscode://file/<absolute-sidecar-path>` deeplink. Works with VS Code, Cursor, Windsurf. Available for both populated and empty-state sidecars.
- **JSON API for tag mutations.** New `skills/quest/server.py` replaces `python3 -m http.server`. Still binds to `127.0.0.1` only.
  - `POST /api/tags/add` `{project, id, tag}` — `tag` accepts a comma list
  - `POST /api/tags/remove` `{project, id, tag}`
  - `POST /api/tags/bind` `{project, id, name?}` — auto-prefixes `session:`
  - `POST /api/tags/unbind` `{project, id}`
  - `GET /api/session` — diagnostic
  - Single writer lock, atomic JSON write, in-process re-render after each mutation.

### Changed

- **`systemd/quest-dashboard.service` updated** to run `server.py` instead of `python3 -m http.server`. Same port, same localhost binding, same hardening flags.
- **Render layer**: `tags_str` / `tags_pretty` / `session_tags_html` now always default to empty string. Previously, quests with no `tags` field rendered the literal `{{q.tags_str}}` marker (the engine intentionally leaves missing fields visible as a debug aid — but `tags` is an optional field that should render quietly when absent).

### Internal

- `session_tags_html` is pre-rendered Python-side and injected via `{{{...}}}` triple-brace raw inject. The template engine's non-greedy `{{#each}}` regex doesn't support nested loops — same trick already used by `live_claims_html`.
- Single shared tag validator: `^[A-Za-z0-9_:./\-]{1,64}$`. Colon allows `session:limor:s2`; dot allows `v1.2`; slash allows `area/auth`.

## [1.8.0] — 2026-05-14

User-authored "My To-Do" sidecar + fenced-code diagram blocks.

### Added

- **My To-Do — per-quest user task sidecar.** A markdown file per quest at `~/.claude/quest/data/notes/<proj>__<quest>.md` holds your own todos + free-form notes, separate from the plan-derived task sections. Write `- [ ]` checkboxes directly in the file, or use the new `/quest todo` subcommand: `add`, `done`, `undone`, `rm`, `note`, `list`, `edit`. Renders as a green "My To-Do" section on the plan-card — open by default, empty-state hint when blank. autosync never plan-parses it; a write only triggers a re-render.
- **Fenced code blocks in action bodies** — triple-backtick blocks in `## Section 13/14` action bodies render as monospace `<pre class="qd-diagram">` panels, so ASCII diagrams and visual maps stay aligned.
- **Engine test suite** — `test_*.py` files alongside the engine (sidecar parser, `/quest todo` CLI, render layer, autosync notes-branch, integration) — 60 assertions.

### Changed

- Retired the unused `_user-tasks.html.tmpl` partial — superseded by the directly-writable My To-Do section.

### Internal

- New `sidecar.py` module — pure-function sidecar markdown parser + targeted file-edit helpers, shared by `quest.py` and `render.py`.

## [1.7.0] — 2026-05-13

AI-resume briefings, link buckets, normalized type scale, live-claim pills.

### Added

- **Five new optional quest fields** for handoff to a fresh AI/human reader:
  - `resume_context` — paragraph addressed to whoever picks the quest up cold.
  - `files_touched` — list of `{path, role}` describing the relevant files.
  - `commands` — list of `{cmd, purpose}` for tests, deploys, etc.
  - `gotchas` — list of "don't repeat — already failed" strings.
  - `repo` — absolute path to the working dir.
- **"Copy briefing" button** on the plan card. Copies a self-contained markdown briefing (project, status, brief, why, outcome, done/todo actions, resume context, skills, files, commands, gotchas, links) to the clipboard. Paste into a fresh AI session to resume work.
- **Per-quest `.md` endpoint**: each quest is rendered to a static markdown file at `/<project>/quest-<id>.md` and `/<project>/<id>.md` so an AI can `WebFetch` the briefing directly.
- **Auto-bucketed links** in the Links section. URL pattern routes links into 6 collapsible groups: Try it · Code & commits · Learning entries · Project rules · Skills · Plan. Empty buckets hide automatically.
- **Live-claim pills** on the quest-log page. For every active quest, shows a small "live: `<name>`" row listing the chosen names of CC sessions currently claiming the quest. Hidden when no sessions are working on it.
- **Sidecar `.name` file** written next to each `.quest` claim by `/quest claim --session-name`. Survives independent of quest JSON mutations and supports multiple live sessions on the same quest (each session has its own sidecar).
- **Name-based auto-claim**: `/quest claim --session-name <slug>` now substring-matches the slug against active quest ids before falling back to most-recently-touched. Launch `claude --name build-login` and the quest containing "build-login" gets claimed.
- **Render-time soft warn** lists active quests missing core fields (desc / kpi / why / next_step) to stderr. No block, just visibility.

### Changed

- **Type scale normalized** to 6 tiers (`xl 36 / lg 22 / md 18 / base 15 / sm 13 / xs 12`). Previous CSS declared 13 different font sizes across templates with conflicting cascade; an override block at end of `<style>` collapses everyone to the tier scale.
- **Symbols dropped from headings** (`▸ ⚔ ✏` and em-dash chrome around section labels). Status pill renders title-case (`Active` not `ACTIVE`). Tags display with ` · ` separator and hyphens-to-spaces.

### Fixed

- **"TODO TODO TODO" empty preview rows** when a quest uses legacy `tasks[]` with `label` instead of `title`. The tasks→actions synthesizer now accepts both field names.
- **Double-prefixed plan path** (`Plan file: ~/.claude/plans//home/<user>/.claude/plans/<file>.md`) when a quest's `plan` field was stored as an absolute path. `render.py` now normalizes plan paths to filename only.

## [1.6.2] — 2026-05-10

Plan-card render bug fixes surfaced by real quest data.

### Fixed

- **Empty `Plan file:` footer** when a quest's `plan` field is `""` — the per-quest template emitted `Plan file: ~/.claude/plans/` with nothing after the slash. Now wrapped in `{{#if active.plan}}` so the line is omitted entirely when no plan is set. Both pokemon and storybook themes.
- **Literal `{{q.url}}` / `{{q.label}}` template tokens** rendered in the Links section when a quest stored `links` as bare strings instead of `{url, label, desc}` objects. `render.py` now normalizes every link entry: dicts pass through with safe field fallbacks; strings become `{url, label, desc: ""}` so the partial's `{{#each}}` body resolves cleanly.
- **X-axis overflow on plan-card** when KPI text was a 300+ char sentence. The KPI lived in a `.qd-pill` with `white-space: nowrap`; without `min-width: 0` the flex item refused to shrink and pushed the card past the 1280px frame. Fix in both themes: pills now allow flex shrink, and `.qd-pill-kpi` uses `white-space: normal` + `overflow-wrap: anywhere` so long KPI sentences wrap to multiple lines instead of clipping or overflowing.
- **Long unbroken URL paths** in `.qd-link-label` (e.g. a deep `~/.../active/some-long-thread-name.md` path) caused horizontal overflow because the grid column was `1fr` (which won't shrink unbreakable tokens) and the label had no overflow handling. Both themes now use `grid-template-columns: minmax(0, 1fr) auto` and the label has `min-width: 0; overflow-wrap: anywhere; word-break: break-word`.

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

Session identity = `(claude_pid, /proc/<pid>/stat field-22 starttime ticks)` — deterministic per CC instance, with no external dependency.

`claimed_session_name` field on a quest gets stamped at claim time. The plan-card `<h2>` title renders `Quest Name (session-name)` when the kebab-cased session name differs from the quest id; otherwise just the quest name (no duplicate).

A standalone helper script for the Claude Code statusline (`scripts/statusline-quest.sh` in the public repo) emits a clickable OSC-8 hyperlink: `quest: <project>/<quest-id> · <session-name>` linking to the plan-card URL. Modern terminals (Windows Terminal, iTerm2, kitty, recent VS Code, Ghostty) render the tag as a single-click link. `STATUSLINE_COMPACT=1` env var collapses everything onto one line for short terminals.

### Added — `paths_map` separator-aware matching

Auto-detect now matches a path_map prefix when cwd is exactly the prefix OR starts with `prefix` followed by a separator (`/`, `-`, `_`). One entry like `~/my-project` covers all sibling worktrees `my-project-feature`, `my-project-staging`, etc. without overmatching `my-project2`. Resolved project is also validated against `quests.json` — aspirational path_map entries that don't have a corresponding dashboard project fall through to the dashboard root instead of emitting a 404 link.

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

[1.8.0]: https://github.com/ytrofr/claude-code-quest/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/ytrofr/claude-code-quest/compare/v1.6.2...v1.7.0
[1.5.0]: https://github.com/ytrofr/claude-code-quest/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/ytrofr/claude-code-quest/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/ytrofr/claude-code-quest/compare/v1.2.0...v1.4.0
[1.2.0]: https://github.com/ytrofr/claude-code-quest/releases/tag/v1.2.0
