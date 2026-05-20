# Quest "My To-Do" — user-authored tasks on quest cards

> **Spec** · 2026-05-14 · status: DRAFT (awaiting user review)
> **Component**: `~/.claude/skills/quest/` (quest dashboard engine)
> **Brainstorm artifacts**: `~/quest-todo-design/.superpowers/brainstorm/`

---

## 1. Problem

Every task/step section on a quest plan-card today — "Your Actions" (§14), "Claude's
Actions" (§13), "Deeds (Claude)" (legacy §13 checkboxes), "To-Do (You)" (legacy §14
checkboxes) — is **downstream of a plan markdown file**. `autosync.py` parses the plan
and writes those fields. There is no way for the user to jot a task or note directly
against a quest. Worse, "To-Do (You)" / `tasks_user[]` is an orphan: it renders but
nothing writes it (no CLI command; autosync now routes §14 into "Your Actions").

The user wants: a section they write **directly** (low friction, natural writing),
that **Claude reads easily**, that survives `autosync` rewrites, and that Claude
**reliably knows to consult** when asked about a quest's todos / backlog / roadmap.

## 2. Solution (chosen approach — "Journal + Log")

A **per-quest markdown sidecar file** the user owns completely, edited two ways:

- **directly** — open the file, write `- [ ]` lines + free notes; or
- **via CLI** — `/quest todo add|done|undone|rm|note|list|edit` thin commands that
  make targeted line edits to the same file.

Rendered as a **"My To-Do"** section on the plan-card (open by default, green accent
to mark it as the user's). Read by Claude through a **three-layer integration** so any
session — cold or warm — knows the feature exists and when to use it.

Rejected alternatives:
- **A — file only** (no CLI): no quick-add from a session, Claude can't jot for the user.
- **B — `my_tasks[]` JSON field + CLI only**: a command per task, no free-form notes,
  not "natural writing". Simpler, but fails the stated UX need.

## 3. Data model — the sidecar file

### 3.1 Location

```
~/.claude/quest/data/notes/<project-id>__<quest-id>.md
```

`<project-id>` and `<quest-id>` are already kebab-safe slugs (`slug()` collapses `_`/`-`
runs to a single `-`), so a quest id can never contain `__` — the `__` separator is
collision-proof.

### 3.2 File format

```markdown
# My To-Do — <quest name>

- [ ] Ask Yannai about the staging API key
- [x] Renamed the feature branch
- [ ] Double-check the Hebrew date parsing edge case

## Notes

The soak window ends Friday — don't promote before then.
```

### 3.3 Parsing rules (`parse_sidecar(text) -> dict`)

Pure function. Deterministic. No I/O.

- **Todo lines**: `^\s*-\s*\[( |x|X)\]\s*(.+)$` → `{title, done}`. `done` true if `x`/`X`.
  Order preserved = file order. 1-based index used by the CLI.
- **Notes**: everything under a `## Notes` heading (case-insensitive) until EOF or the
  next `##`. Rendered as HTML-escaped text, `<br>` on single newline, blank line =
  paragraph break. **No markdown parsing in v1.**
- **Everything else** (the `#` header, other prose, other headings) — ignored by the
  parser but **preserved in the file** (CLI never does a full-file rewrite).
- Returns `{todos: [...], notes_html: str, has_content: bool}`.

### 3.4 Why this store

`autosync.py` only ever reads plan files under `*/plans/*.md`. The sidecar lives under
`quest/data/notes/` — autosync never looks there. The sidecar is **autosync-immune by
construction**, not by a tag or a guard. This mirrors the proven existing pattern:
manual `--add-link` entries survive autosync because they're structurally distinct from
`source: "autosync"` entries.

No `quests.json` schema change.

## 4. CLI — new `todo` subcommand

`python3 quest.py todo <action> <project> <quest> [args]`

| Action | Behaviour |
|---|---|
| `add <proj> <quest> "title"` | Validate proj+quest exist (`get_project`/`find_quest`); create file with `# My To-Do — <name>` header if missing; append `- [ ] title` after the last checkbox line (or after header if none); `render_now()`. |
| `done <proj> <quest> <n>` | 1-based; flip Nth checkbox `[ ]`→`[x]`; clean error if N out of range; `render_now()`. |
| `undone <proj> <quest> <n>` | `[x]`→`[ ]`; `render_now()`. |
| `rm <proj> <quest> <n>` | Delete the Nth checkbox line; `render_now()`. |
| `note <proj> <quest> "text"` | Append a line under `## Notes` (create the heading if absent); `render_now()`. |
| `list <proj> <quest>` | Print file contents + absolute path. No render. |
| `edit <proj> <quest>` | Print the absolute file path only (user opens in their editor). No render. |

**Invariants**:
- All edits are **targeted line edits**, never full-file rewrites — free-form content
  the user wrote between checkboxes is preserved.
- Quest existence is validated **before** any file is created — a typo'd quest id
  errors out instead of leaving an orphan sidecar.
- `add`/`done`/`undone`/`rm`/`note` re-render; `list`/`edit` do not.

## 5. Render integration (`render.py`)

- **`precompute()`** (project-scope, ~line 172): for each quest, attempt to load
  `notes/<pid>__<qid>.md`. On hit, set: `my_todo` (list of
  `{title, done, done_class, done_mark}`), `my_todo_done`, `my_todo_total`,
  `my_todo_next` (first undone title, truncated ≤80), `my_notes_html`,
  `my_todo_has=True`. On miss, `my_todo_has=False`.
- **`QUEST_SCOPE_KEYS`** (~line 84): add the `my_todo*` / `my_notes_html` keys.
- **`_quest_scope()`** (~line 900): pop `my_todo*` keys when a quest has no sidecar —
  mirrors the existing `tasks_user` popping (lines 924-927) so one quest's todos never
  leak into another quest's plan-card block.
- **New partial** `themes/_shared/_my-todo.html.tmpl`:
  `<section class="qd-my-todo"><details data-qd-collapse="my-todo" open>…`. **Open by
  default** (still collapsible; collapse-state persists via existing JS). Empty-state
  branch when `my_todo_has` is false — a one-line hint showing the `todo add` command,
  consistent with the `_actions-claude` empty state.
- **Template insertion**: add `{{> _my-todo}}` to `themes/pokemon/_plan-card-quest.html.tmpl`
  and `themes/storybook/_plan-card-quest.html.tmpl`, after `{{> _taskslist}}`
  (the `{{> _user-tasks}}` line is removed — see §7).
- **Theme CSS**: add a `.qd-my-todo` block to `themes/pokemon/plan-card.html.tmpl`
  (green accent, ~`#2e9a5a`) and `themes/storybook/plan-card.html.tmpl`
  (theme-appropriate). A theme missing the CSS still renders functional, just unstyled.
- **`briefing_md`**: append a "My To-Do" section listing open items, so the card's
  "Copy briefing" button carries the user's list when pasted to Claude.

All todo titles + notes are **HTML-escaped** — the sidecar is untrusted user input.

## 6. Autosync isolation + hook extension

`autosync.py` needs no change to *avoid* the sidecar (it already only reads plan
files). But manual sidecar edits leave the pre-rendered dashboard **stale**. Fix:

- **`~/.claude/hooks/quest-plan-autosync.sh`**: add `*/quest/data/notes/*.md)` to the
  `case "$FILE"` block → fork `autosync.py` with the notes path.
- **`autosync.py`**: in `main()`/`autosync()`, if the path is under `quest/data/notes/`,
  branch to a **render-only** path (`render_now()` then return) — skip all plan-parsing
  logic.

This covers sidecar edits made through Claude Code's Edit/Write tool automatically.
Edits in a fully external editor are covered by the fallback: any `/quest todo`
command, or `/quest render`, re-renders. Documented in SKILL.md.

## 7. Cleanup — retire the orphan (scoped tight)

- Remove `{{> _user-tasks}}` from `themes/pokemon/_plan-card-quest.html.tmpl` and
  `themes/storybook/_plan-card-quest.html.tmpl`.
- Delete `themes/_shared/_user-tasks.html.tmpl`.
- **Leave `render.py`'s `tasks_user` plumbing alone** (lines ~481-483, 540-554, 917,
  924-927). It's a harmless legacy bridge (`tasks_user` → `actions_user` conversion);
  ripping it out has wider blast radius and is a separate optional cleanup. Minimal
  removal = lowest risk.

## 8. Three-layer integration — "know it by heart"

`SKILL.md` loads only on `/quest` invocation, so the feature cannot live only there.

### Layer 1 — always-on rule (`~/.claude/rules/projects/quest-dashboard.md`)

Loaded every turn. Add (~8-10 lines, kept tight):
- One line: sidecar lives at `quest/data/notes/<proj>__<quest>.md`, user-owned,
  autosync-immune.
- NL triggers (added to the existing "NL Triggers" section):
  - "add todo X to quest Y" / "remind me to X on Y" → `/quest todo add`
  - "mark my todo N done on X" → `/quest todo done`
  - "read quest X's task list / todos / backlog", "what's on the backlog/roadmap for X",
    "what's left on X", "what do I need to do on X", "show me my todos" → **Backlog
    Read Routine** (§9)

Cost: permanent every-turn tokens. Justified by the explicit "know by heart"
requirement, which overrides the general minimize-always-on guidance. ~8-10 lines is
the floor.

### Layer 2 — skill (`~/.claude/skills/quest/SKILL.md`)

Loads on `/quest` or any resume. Add:
- Section **"My To-Do — user-authored tasks"**: file location, format, parse rules,
  all `todo` commands, the stale-dashboard note + `/quest render` fallback.
- Section **"Backlog Read Routine"** (§9).
- A **mandatory step** added to the existing **Resume Routine**: `Read` the sidecar,
  surface open todos in the summary; the output template gains a
  `Your open to-dos: <n> open — <first 3>` line (or `none`).

### Layer 3 — routines

The Resume Routine reads the sidecar as a mandatory step (above). The Backlog Read
Routine (§9) is the on-demand read path. Both live in the skill; both are *reached*
via Layer-1 triggers, so a cold session still gets there.

## 9. Backlog Read Routine (new — parallel to the Resume Routine)

Triggered by the Layer-1 phrasings ("read quest X task list", "backlog", "roadmap",
"todos", "what's left", "what do I need to do"). Steps:

1. **Resolve target** — a quest id / number / name, or a whole project. Same
   nearest-match resolver the Resume Routine uses; fail loud with nearest matches on a
   miss.
2. **Read** `quests.json` + the sidecar file(s).
3. **Present the consolidated task picture**:
   - **My To-Do** (the sidecar) — open + done counts, open items
   - Plan-derived sections — Your Actions / Claude's Actions / Deeds — current state
   - `next_step`
   - For a project-scope ask: repeat for every `current` (and optionally `locked`)
     quest.
4. **Read-only** — never mutates. Safety Invariant I1 untouched.

## 10. Edge cases (validated)

- **Quest renamed**: `id` is set only at `add` time, never changed by `update --name`.
  Sidecar filename (keyed on `id`) survives. The `# My To-Do — <name>` header goes
  stale (cosmetic) — documented, not auto-refreshed in v1.
- **Quest archived** (`quest reset` → `chapters[]`): sidecar file is orphaned but
  harmless — zero data loss. No v1 cleanup (YAGNI); documented.
- **Filename safety**: `__` separator collision-proof (see §3.1).
- **Untrusted input**: all titles + notes HTML-escaped in render.
- **Empty / missing sidecar**: section renders an empty-state hint with the `todo add`
  command.
- **CLI on a nonexistent quest**: validated before any file creation — no orphan files
  from typos.
- **Concurrency**: read-modify-write, last-write-wins. Acceptable for a personal todo
  file; documented.

## 11. Test plan

### Tier 1 — deterministic (TDD, write tests first)

- **`test_my_todo_parser.py`**: empty file, checkboxes only, checkboxes + notes,
  `[x]`/`[X]`/`[ ]`, malformed lines, HTML-injection in a title, Hebrew/unicode, blank
  file, `## Notes` present/absent.
- **`test_todo_cli.py`**: `add` creates file with header / appends / preserves
  free-form content between checkboxes; `done`/`undone`/`rm` by 1-based index;
  out-of-range N errors cleanly; `todo` on nonexistent project/quest errors before
  file creation; `note` appends under `## Notes`, creating the heading if absent.
- **Render**: precompute loads sidecar → correct `my_todo*` scope keys; missing file →
  `my_todo_has=False` → empty-state; HTML escaping; `_quest_scope` pops keys for
  quests without a sidecar.
- **Hook**: pipe `{tool_input:{file_path:".../quest/data/notes/x.md"}}` → asserts a
  render-only fork; pipe a non-matching path → `exit 0`.

### Tier 2 — integration

- `render.py --dry-run` produces valid HTML containing the `_my-todo` section.
- Round-trip: `todo add` → render → grep the generated HTML for the todo text.
- Orphan-removal regression: render every existing project, confirm no card breaks
  from the `_user-tasks` removal.

### Tier 3 — behavioral (the "know it by heart" layer)

- **Structural (deterministic)**: grep the always-on rule for every trigger phrasing;
  grep `SKILL.md` for the "My To-Do" + "Backlog Read Routine" sections; grep the
  Resume Routine for the sidecar-read step. Asserts the integration text *exists*.
- **Behavioral (probabilistic)**: documented probe checklist — in a fresh session,
  (a) paste a quest URL whose quest has a sidecar → todos must appear in the resume
  summary; (b) say each trigger phrasing → the right routine/command must fire. Run a
  handful of times; if triggering is weak, iterate the rule wording. This is the
  `a-b-c-variant-experiment` / `anthropic-eval-best-practices` pattern.

## 12. Confidence

- **Mechanical layers (parser, CLI, render, hook): high.** Deterministic, test-first.
- **Behavioral layer ("Claude reliably uses it"): moderate** — verifiable only by
  probe, never by a binary test. This is inherent to instruction-shaping, not a flaw
  in the design. Mitigation: instrument-first, measure, iterate the rule text (cheap —
  it's text, not code).
- **Safe to ship despite the moderate behavioral confidence**: purely additive, no
  `quests.json` schema change, kill switch is one line (remove `{{> _my-todo}}`), and
  sidecar files are inert if rendering is disabled.

## 13. Scope

### In scope (~10 files)

- `quest.py` — `cmd_todo` + argparse subparser
- `render.py` — sidecar load/parse in `precompute`, scope keys, `_quest_scope` pop,
  `briefing_md` addition
- `themes/_shared/_my-todo.html.tmpl` — new partial
- `themes/pokemon/plan-card.html.tmpl` + `themes/storybook/plan-card.html.tmpl` — CSS
- `themes/pokemon/_plan-card-quest.html.tmpl` + `themes/storybook/_plan-card-quest.html.tmpl`
  — insert `{{> _my-todo}}`, remove `{{> _user-tasks}}`
- `themes/_shared/_user-tasks.html.tmpl` — delete
- `~/.claude/hooks/quest-plan-autosync.sh` — notes-path case branch
- `~/.claude/skills/quest/SKILL.md` — My To-Do + Backlog Read Routine sections, Resume
  Routine step
- `~/.claude/rules/projects/quest-dashboard.md` — Layer-1 triggers + sidecar fact
- `tests/` — `test_my_todo_parser.py`, `test_todo_cli.py`, render/hook test additions

### Out of scope (v1)

- Rendering "My To-Do" on quest-log or home-index (plan-card only).
- Markdown formatting inside notes (plain text + `<br>` only).
- Auto-refreshing the sidecar `#` header on quest rename.
- Cleaning up orphaned sidecars when a quest is archived.
- Removing `render.py`'s legacy `tasks_user` plumbing.

## 14. Known risk — parallel-work contention

At spec time, `autosync.py`, `themes/pokemon/plan-card.html.tmpl`, and
`themes/storybook/plan-card.html.tmpl` are **already modified** in the working tree
(uncommitted, another session's work). All three are files this design modifies.
Before implementation: coordinate via the inter-agent bus or wait for that work to
land — per `~/.claude/rules/process/multi-agent-safety.md`. Do not implement over
uncommitted peer changes.

## 15. Post-validation (filled at implementation time)

_To be completed by the implementation plan + execution._
