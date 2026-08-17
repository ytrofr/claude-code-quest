---
name: quest
description: "Manage RPG-style project roadmaps — quests.json + themed HTML dashboard at http://localhost:8770. Use when adding/updating/completing a quest, switching a project's theme, or asking 'what's the status of my projects?'."
user-invocable: true
allowed-tools: "Bash, Read"
argument-hint: "<status|init|add|update|done|theme|style|render|reset|chapters> [args]"
---

# /quest — RPG-style project roadmap

Visualize your projects as gamified RPG maps. Each project gets a themed dashboard view: an overworld map, a quest log, and a per-quest plan card.

**Single source of truth**: `~/.claude/quest/data/quests.json`. Two built-in themes: **pokemon** (top-down regional map) and **storybook** (illuminated parchment). Renderer outputs HTML at `~/.claude/quest/site/<project>/{route,quest-log,plan-card}.html`. Localhost service at **http://localhost:8770** serves the dashboard and auto-starts on boot.

## 🚨 ABSOLUTE PROHIBITION — `--clean` requires LITERAL operator command

**This rule supersedes everything else in this skill. Read it before any `quest reset` invocation.**

**Claude MUST NEVER pass `--clean` to `quest reset` unless the operator has LITERALLY typed `--clean` OR explicitly said "wipe locked too" / "include locked" / "delete locked quests" in the current conversation.**

- Default `quest reset <project> --chapter <name> --yes` is correct in 99% of resets. Locked quests survive by design — they are the operator's backlog.
- "fresh start" / "clean reset" / "wipe everything" / "reset clean" are AMBIENT PHRASES — they do NOT authorize `--clean`. The flag preserves the operator's future work; ambient phrases routinely mean only "archive the done+current set."
- If you find yourself typing `--clean` and the operator hasn't TYPED the word "--clean" OR an equivalent literal demand, **STOP**. Run without the flag. Locked quests will survive, which is what the operator actually wants 99% of the time.

**Verification gate** — before invoking `quest reset` with `--clean`:

1. Grep the conversation: did the operator type `--clean` literally? If no → drop the flag.
2. Did they say a phrase that unambiguously means "destroy locked quests too"? If unsure → ASK before running.
3. Default to the safe path. Re-adding `--clean` later is one command; restoring 25 locked quests is a multi-step manual JSON patch.

### Failure log — why this rule is in screaming red

**2026-05-11 (OGAS, Phase 9 → Phase 10 pivot)**: Claude ran `quest reset ogas --chapter phase-9-archived --clean --yes` during a routine reset. Operator had NOT typed `--clean` and had NOT authorized wiping locked quests — they had asked for a "fresh new session" framing the Phase 10 pivot. The `--clean` flag archived 25 LOCKED future-work quests, including one (#21) the operator was actively waiting on. The loss only surfaced when they went looking for that quest and found it gone. Restoration required manual JSON patching of 25 entries. Operator's verbatim demand: **"YOU NEVER EVER EVER DO THIS UNLESS I SAY EXPLICITLY."** This was a VIOLATION of Safety Invariant I1 below, which already covered the case — Claude had the rule loaded and ran the command anyway. Making the rule more prominent and adding this failure log.

---

## ⚠️ Safety Invariants — READ BEFORE ANY MUTATION

**Three rules. Always-on machine rule `~/.claude/rules/projects/quest-dashboard.md § Safety Invariants` is the canonical condensed form — this is the full detail.**

### I1 — Permission gate on destructive mutations

NEVER run any of these without an operator command containing BOTH the project id AND one of the destructive verbs: `reset` / `archive` / `wipe` / `clear` / `delete` / `demote` / `remove` / `purge` / `erase` / `unarchive`.

| Operation                                                                                           | Why permission required                                                                |
| --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `quest reset <proj> --chapter <name>` (with `--yes`/`-y`)                                           | Archives done+current quests; can move N>5 quests off live map                         |
| `quest reset <proj> --chapter <name> --clean`                                                       | **NEVER without operator literally typing `--clean`** — see Absolute Prohibition above |
| `quest update <proj> <q> --status locked` on a `current` quest                                      | Demotes a quest in flight                                                              |
| `quest update <proj> <q> --status current` on a `done` quest                                        | Un-promotes (rewrites history)                                                         |
| Re-using `--chapter <name>` for an existing chapter                                                 | Appends to existing chapter — could double-archive                                     |
| Direct edit of `quests.json` moving quests between `quests[]` and `chapters[]`, or removing entries | No CLI guard rails                                                                     |

**Soft-warn FIRST** if the operation will archive >5 quests OR touch any `current`-status quest. List affected quest IDs + names + statuses. ASK before executing. Ambient operator phrasing ("clean up old quests", "tidy the map", "fresh start") is NOT explicit enough — require the operator to literally name the project + destructive action.

The CLI's preview-by-default `quest reset` (requires `--yes` to actually archive) is one layer of safety; this rule is the agent-level layer on top.

**Safe to run autonomously** (no explicit permission required):

- `init`, `add`, `update` (tasks/links/progress/next_step/branch/last_commit/tags/blockers/effort/desc/why/kpi)
- `update --progress 1.0` and `done` (forward progression: current → done)
- `theme`, `style`, `render`, `chapters` (list-only), `status` (read-only)

### I2 — Plan-derived title is the source of truth

Priority for new quest `name`:

1. **Operator explicit name wins always**: "create a quest called X" / "title it X" / "name it X" → `name = X` verbatim. `id` = kebab-case of `name`.
2. **Plan H1**: if the work has a plan file (`~/.claude/plans/*.md` or project `plans/`), extract the H1. Accept both `# Plan: <title>` and bare `# <title>` shapes. `name = <title>`. `id` = kebab-case of `name`.
3. **No plan AND no operator name**: ASK the operator for the canonical title BEFORE creating. Do NOT auto-derive from session-internal jargon (`§23`, `Phase 7B`, `Wave 15a`, `Bundle F3`, etc.) — that's not user-facing identity.

**Forbidden**: deriving the `id` from the plan FILE name. Plan `~/.claude/plans/i-want-to-plan-pending-layout-queue.md` → BAD id `i-want-to-plan-pending-layout-queue`. The file name is the prompt that birthed the plan; the H1 is the title.

**Autosync exception — the file-name DOES become the id.** `autosync` (fired on any write of a plan file carrying `**Project**: <id>`) creates a quest whose `id` = kebab of the plan **file name** — the one path that violates the rule above. Consequence: writing a plan file AND hand-creating a quest with a different id → autosync spawns a DUPLICATE stub (missing kpi/why/next_step). **Mitigation**: name the plan FILE to match your intended quest `id`. If they already diverged, `mv` the file to match, then delete the stub (destructive — operator OK per I1). Evidence: 2026-05-14 — `<quest-id>-multi-model.md` auto-spawned a dup of the hand-built `<quest-id>`; fixed by renaming the file.

### I3 — Full schema payload on every `add` — NEVER stub

Every quest creation MUST populate these fields. Missing fields = stub = operator must repair later = drift:

| Field          | Source / minimum                                                                                                   |
| -------------- | ------------------------------------------------------------------------------------------------------------------ |
| `name`         | Plan H1 or operator-given (I2). REQUIRED                                                                           |
| `id`           | kebab-cased from `name`. REQUIRED                                                                                  |
| `desc`         | 1-2 sentence summary of the work. REQUIRED                                                                         |
| `landmark`     | one of house/tower/mill/bridge/camp/cave/castle. REQUIRED                                                          |
| `status`       | current / locked / done. REQUIRED. **"Current" is plural — never auto-lock just because another quest is current** |
| `progress`     | 0.0-1.0 realistic estimate (0.0 if unstarted). REQUIRED                                                            |
| `xp_reward`    | 25 default; scale with effort. REQUIRED                                                                            |
| `plan`         | full path to plan file, or empty string if none. REQUIRED                                                          |
| `next_step`    | one concrete next action. NEVER empty                                                                              |
| `why`          | 1-3 sentences stating the PROBLEM (not the solution). REQUIRED                                                     |
| `kpi`          | 1 sentence: how success is measured. REQUIRED                                                                      |
| `tasks[]`      | extracted from plan §13 Post-Validation checkboxes, OR session milestones. MIN 3 items                             |
| `tasks_user[]` | REQUIRED WHEN APPLICABLE — quest has operator-facing actions (decisions/approvals/eyeball gates). Extracted from plan §14 User Actions checkboxes by autosync. Renders as "Your Actions" on the card; `tasks[]` renders as "Claude's Actions". |
| `branch`       | `git branch --show-current` of the working directory. REQUIRED if work is on a branch                              |
| `last_commit`  | `{sha, msg, date}` from `git log -1` of the work area. REQUIRED if any commits exist                               |
| `tags[]`       | 3-7 keyword tags                                                                                                   |
| `links[]`      | MIN 3: (a) dogfood/live URL where the work is exercised, (b) commit URL, (c) plan file path                        |
| `depends_on[]` | quest IDs this work waits on; empty array `[]` is OK                                                               |
| `blockers[]`   | open blocker descriptions; empty array `[]` is OK                                                                  |
| `effort`       | `{estimate_hr, actual_hr}` — best estimates, refine on update                                                      |

Stub quests (`/quest add <proj> "<name>" --next "..."` and nothing else) are FORBIDDEN. If the operator hasn't given enough context to populate the full schema, ASK before creating — same gate as I2.

## 🔗 Resume Routine — Quest URL Trigger

**When the operator pastes** `http://localhost:8770/<proj>/plan-card.html?q=<qid>` in any session (including fresh sessions with no prior context), execute this routine WITHOUT asking. It is READ-ONLY — no permission needed (does NOT touch Safety Invariant I1).

### Hook enforcement (post-2026-05-15)

The claim step is now **hook-enforced** via `~/.claude/hooks/quest-url-rebind.sh` (UserPromptSubmit). When the URL appears in a prompt, the hook automatically invokes `python3 ~/.claude/skills/quest/quest.py claim <proj> <qid>` BEFORE the model sees the turn, and writes two sentinels under `~/.claude/quest/run/`:

- `session-<sk>.url-locked` (60s) — `prompt_rebind_scorer.py` reads this and short-circuits, preventing IDF token overlap from silently undoing the URL claim in the same turn
- `session-<sk>.canary-suppressed-until` (5min) — `statusline-quest.sh` reads this and skips the `⚠` drift glyph since the mismatch is INTENTIONAL post-rebind

The hook also emits additionalContext directing the model that the FIRST tool call MUST be `Read <quest.plan>`. **Model still runs Steps 2-7 below** for the summary + probes + confirmation; the hook just guarantees Step 1's claim side-effect happened regardless of model attention. Kill switches: `QUEST_URL_AUTOCLAIM_DISABLED=1` or `touch ~/.claude/quest/url-autoclaim-disabled`. Recurrence-prevention rule: `~/.claude/projects/-home-ytr/memory/feedback_quest_reclaim_on_topic_shift_2026-05-15.md`.

### Step-by-step

1. **Parse**: extract `<proj>` and `<qid>` via regex `localhost:8770/([a-z][a-z0-9_-]*)/plan-card\.html\?q=([a-z0-9_-]+)`.
2. **Resolve quest**: read `~/.claude/quest/data/quests.json`. Search `projects.<proj>.quests[]` for entry with `id === <qid>`.
   - Miss? Search `projects.<proj>.chapters[*]` for archived hit.
   - Still miss? Fail loud — list 3 nearest matches by string distance. Do NOT guess.
3. **Read plan + My To-Do sidecar**: if `quest.plan` is non-empty AND the file exists, `Read` it fully (most plans live at `~/.claude/plans/<name>.md`). ALSO `Read` the My To-Do sidecar `~/.claude/quest/data/notes/<proj>__<qid>.md` if it exists — the operator's own todos/notes for this quest.
4. **Git state — MANDATORY verification, NOT cached-data quoting**:

   ```bash
   git log -1 --format=%h    # CURRENT working-tree HEAD
   git log --oneline -5      # context
   git status --short        # local dirt
   git branch --show-current # current branch
   ```

   **MANDATORY check**: `git log -1 --format=%h` MUST match `quest.last_commit.sha`. If mismatch → flag `git_verified: drift (working=<X>, quest=<Y>)` in summary. Compare current branch to `quest.branch`. Warn if mismatch — do NOT auto-switch. NEVER quote `quest.last_commit.sha` from the JSON as ground truth without this verification — the cached value drifts.

5. **Live state probes — MANDATORY (failure OK and surfaces; SKIPPING FORBIDDEN)**:
   - **Dogfood URL probe** (HEAD with GET fallback): if `quest.links[]` has a dogfood URL on `localhost:8000`, run `curl -sI -m 3 -o /dev/null -w "%{http_code}" <url>`. Any HTTP response code (2xx/3xx/4xx) → `dogfood_reachable: yes (<code>)`. Only `000` or no response → `dogfood_reachable: no (timeout/refused)`. Don't treat 4xx as failure — the server is up.
   - **Peer bus scan** (search active thread bodies — sorted by recency, NOT alphabetical; telemetry at `log/v2/*.jsonl` is NOT the target):
     ```bash
     # Sort active/*.md by mtime DESC, grep for project/quest mention, take top 3
     ls -t ~/shared/inter-agent/active/*.md 2>/dev/null | \
       xargs grep -l -i "<qid>\|<proj>" 2>/dev/null | head -3
     ```
     For each hit, read tail 10 lines and surface in summary: `peer_activity: thread <basename> last <mtime> — "<last message excerpt>"`. If none: `peer_activity: none`. Fallback if no `active/` hits: grep aggregate `~/shared/inter-agent/log.jsonl` for last 5 entries mentioning the project.

   The mtime-sort is critical — alphabetical order surfaces stale threads (`coord-limor-...` before `coord-sigma-s3-s4-20260506-...`). Recent peer activity is what matters for collision detection.
   - These probes COST <1 second total. They are how multi-session coord stays safe — peer s4 may have uncommitted work in shared files; bus scan catches it BEFORE you start work.

6. **Summarize in ≤200 words** using the template below. Summary MUST include `git_verified` + `dogfood_reachable` + `peer_activity` lines (even if "yes/yes/none").
7. **Confirm/proceed**:
   - If `quest.next_step` is an unambiguous action verb (e.g. "run pytest X", "read file Y") → ask "Begin: <next_step>?"
   - If `next_step` requires a choice (e.g. "Pick A or B for…") → present the options.
   - NEVER mark anything `done` — only the operator signals completion.
   - NEVER run destructive ops as part of resume (Safety Invariant I1 still applies).

### Output template (paste-and-modify)

```
Resuming <proj> quest `<qid>` — <name> (#<n>, <status>, <progress*100>%)

**Problem**: <quest.why, 1-2 sentences>
**Success**: <quest.kpi, 1 sentence>

**State** (MANDATORY-verified):
- Branch: <quest.branch> (current: <git branch --show-current> — ✅ match | ⚠ mismatch)
- git_verified: <yes — HEAD SHA <X> matches quest.last_commit.sha> | <drift — working=<X>, quest=<Y>>
- dogfood_reachable: <yes (200) | no (timeout) | n/a (no localhost URL in links)>
- peer_activity: <none | thread <id> last <ts> from <peer> — "<excerpt>">
- Tasks: <N done> / <N total>
- Your open to-dos: <N open — first 3 titles | none> (from the My To-Do sidecar)

**Pending tasks**:
- <first 3 incomplete tasks, by order>

**Plan**: <quest.plan> (read above)
**Top links**: dogfood <URL>, commit <sha>, plan <path>

**Next step**: <quest.next_step>

Begin? (yes / pick different / show more)
```

### Edge cases

| Situation                                            | Action                                                                                                                                  |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| URL has typo in `<proj>` or `<qid>`                  | List 3 nearest matches by string distance. Do not guess.                                                                                |
| Quest in `chapters[]`, not live `quests[]`           | Show chapter name + archived date. ASK before any unarchive action (Safety Invariant I1 applies — unarchive is destructive).            |
| `quest.plan` is empty string                         | Continue with quest data only. Warn "no plan file referenced".                                                                          |
| `quest.plan` path doesn't exist                      | Continue with quest data only. Warn "plan file missing at <path>".                                                                      |
| `quest.branch` ≠ current `git branch --show-current` | Warn before proceeding. Suggest `git checkout <quest.branch>`. NEVER auto-switch.                                                       |
| Multiple quest URLs pasted                           | Handle the FIRST one. Mention "I see N URLs — handling first; reply with others if needed."                                             |
| URL + extra prose ("resume <url>... and also fix X") | URL is primary. After summary, address the extra prose as a follow-up.                                                                  |
| Quest is `status: "done"`                            | Show the summary but ask "this quest is marked done — recreate/extend/different topic?"                                                 |
| `quests.json` file missing or corrupted              | Fail loud. Show `ls ~/.claude/quest/data/quests.json.bak-*` to surface backups. Do NOT auto-restore.                                    |
| Multiple `current` quests in project                 | Normal — `current` is plural. Show all 3 (or however many) with their `next_step` so operator picks which one to begin.                 |
| WebFetch on `localhost:8770/<proj>/...` denied/fails | The URL is only the trigger pattern. We read `quests.json` directly — no fetch required. Note this in routine output so operator knows. |

### Forbidden during resume

- DON'T mark anything `done` — that's operator's signal.
- DON'T run destructive ops (`reset`, `update --status locked` on current, etc.) — Safety Invariant I1 still applies.
- DON'T auto-switch branches — warn only.
- DON'T guess a missing project or quest id — fail loud with nearest matches.
- DON'T modify `quests.json` during resume — read-only.
- DON'T fetch the plan-card URL itself — the URL is a TRIGGER PATTERN, the data lives in `quests.json` + the plan file. Reading the rendered HTML is lossy.
- DON'T quote `quest.last_commit.sha` as ground truth without verifying via `git log -1 --format=%h` — the cached value drifts as commits land in subsequent sessions. **Always verify, never trust cached.**
- DON'T skip the dogfood HEAD probe or peer-bus scan because they "feel optional". They are MANDATORY pre-summary probes — failure is OK and surfaces in the summary, but skipping is FORBIDDEN. The peer-bus scan is how multi-session coordination stays safe.

### Worked example

Operator pastes `http://localhost:8770/ogas/plan-card.html?q=grid-layout-ui-mockup` in a fresh session.

Routine:

```
1. Parse: proj=ogas, qid=grid-layout-ui-mockup
2. Read ~/.claude/quest/data/quests.json → find quest #38, status=current, progress=0.85
3. Read quest.plan: ~/.claude/plans/i-want-to-plan-pending-layout-queue.md (321 lines)
4. MANDATORY git verify:
   - git log -1 --format=%h → "4f3d64e"; quest.last_commit.sha → "4f3d64e" ✅ MATCH → git_verified: yes
   - branch=dev-websites matches quest.branch ✅
   - git status --short → clean (or list uncommitted)
5. MANDATORY live probes:
   - curl -sI -m 3 http://localhost:8000/api/v1/pages/published/... → HTTP 200 → dogfood_reachable: yes
   - grep -l "grid-layout-ui-mockup\|ogas" ~/shared/inter-agent/active/*.md | head -3 →
     finds active/coord-sigma-s3-s4-20260506.md → tail 10 lines →
     peer_activity: thread coord-sigma-s3-s4-20260506 last 2026-05-11T14:04:32Z from sigma:s4 — "v2A v3 PIVOT landed locally. Operator: 'i dont like that the css inspector is a new panel...'"
6. Summarize using template — INCLUDES git_verified + dogfood_reachable + peer_activity lines
7. Ask: "Begin Phase 5 — AST contracts (4 tests) + 4 Playwright E2E? Note: peer sigma:s4 has uncommitted v2A v3 work in shared files."
```

**Key difference from a "best-effort skip" routine**: step 7 surfaces the peer activity to the operator BEFORE work begins. Without the mandatory bus scan, the new session might start Phase 5 work that collides with peer s4's uncommitted page_helpers.py edits.

### Evidence — why these invariants exist

2026-05-11 OGAS Entry #450:

1. Phase 9 pivot session ran `quest reset ogas --chapter phase-7-8-archived` without operator-explicit command. All 34 in-flight OGAS quests archived. No soft-warn surfaced. Operator on next session interpreted as deletion — "where are all OGAS quests gone?!?!?!?!??!". Manual JSON restoration required.
2. Same day, a quest was created as `i-want-to-plan-pending-layout-queue` — the plan FILE name. The actual plan H1 was different. Operator demanded the quest be named what the operator was thinking (`grid-layout-ui-mockup`).
3. Earlier-created quests had only `--next "..."` populated — no `why`, `kpi`, `tasks[]`, `links[]`. Required full re-pack later when context was needed.

All three failure modes encoded into I1/I2/I3.

## Quick reference

| Command                                                | What it does                                                                                       |
| ------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| `/quest status`                                        | Print all projects, dashboard URL, theme list                                                      |
| `/quest hygiene [project]`                             | Read-only noise audit: DUP-RISK collisions, stub quests, codename names (see Hygiene Cleanup Routine) |
| `name_cleanup.py scan/html/apply --project P`          | Fix ugly codename NAMES → short thematic (goal stays in `desc`). Engine `~/.claude/skills/quest/name_cleanup.py` (see ✨ Name Cleanup Routine) |
| `/quest init <project>`                                | Create new project entry                                                                           |
| `/quest add <project> "<name>"`                        | Append a quest                                                                                     |
| `/quest update <project> <quest>`                      | Patch progress, next step, name, links, etc.                                                       |
| `/quest done <project> <quest>`                        | Mark done; awards XP; promotes next locked → current                                               |
| `/quest theme <project> <theme>`                       | Swap theme (e.g. pokemon ↔ storybook)                                                              |
| `/quest style <project> --accent <#hex> --icon <name>` | Set the home-index card accent color and landmark icon (per-project override)                      |
| `/quest render`                                        | Regenerate all HTML                                                                                |
| `/quest reset <project> --chapter <name>`              | **Preview only by default.** Pass `--yes`/`-y` to actually archive. `--clean` archives locked too. |
| `/quest chapters [<project>]`                          | List archived chapters (one or all projects)                                                       |
| `/quest tag <project> <quest> add foo,bar`             | Append freeform tags. Allowed chars: `A-Z a-z 0-9 _ : . / -` (max 64).                            |
| `/quest tag <project> <quest> remove foo`              | Remove a tag.                                                                                      |
| `/quest tag <project> <quest> list`                    | Show all tags on the quest.                                                                        |
| `/quest bind <project> <quest> [--session-name X]`     | Add `session:<name>` linking THIS chat to a quest. Renders a 💬 ribbon on the card image.          |
| `/quest unbind [<project> <quest>] [--session-name X]` | Remove THIS session's tag — from one quest, or every quest carrying it.                            |
| `/quest mine [--session-name X]`                       | List every quest tagged with this session's name.                                                  |
| `/quest claim [<project> <quest>] [--lock]`            | Bind THIS session to a quest. `--lock` freezes the claim — prompt-rebind hook will not auto-switch. |
| `/quest unclaim`                                       | Remove this session's claim — revert to auto-detect (clears lock too).                              |
| `/quest claimed`                                       | Print this session's current claim (or auto-detected fallback).                                    |
| `/quest unlock`                                        | Remove the lock sidecar only — claim file stays. Re-enables auto-rebind.                            |
| `/quest rebind-stats [--days N]`                       | Summarize recent prompt-rebind hook activity. Tune candidates + this session's rebinds.            |

After every mutating command, the renderer runs automatically.

## Prompt-Rebind Hook

Every `UserPromptSubmit` fires `~/.claude/hooks/quest-prompt-rebind.sh` which scores your prompt against the project's current quests and rewrites the claim file when the signal is strong. Sources scored: the user prompt itself + the last assistant message text from `transcript_path`. Two-stage IDF logic:

1. **User-alone** — strong prompt (`score ≥ 5, margin ≥ 3`) rebinds immediately.
2. **Joined fallthrough** — generic "lets do A" prompts get scored together with the prior assistant message; rebind on same threshold.
3. **Conflict guard** — if user signals a different quest than joined picks, downgrade to `suggest` (no auto-rebind).
4. **Suggest** — `score ≥ 3` emits `[quest-hint]` to stdout (visible to Claude as additionalContext) without writing the claim.

### Kill switches

- **Per-session lock**: `/quest claim --lock <proj> <qid>` (or `touch ~/.claude/quest/run/session-<sk>.quest.lock`). Hook honors and logs `acted=locked-skip`. Clear with `/quest unlock`.
- **Global dry-run**: `touch ~/.claude/quest/dry-run` — hook still scores and logs but never writes claim file. `acted=rebound-dryrun`.
- **Hard disable**: `touch ~/.claude/quest/prompt-rebind-disabled` — hook exits at the bash entry point, no scorer invocation.
- **Settings.json removal**: delete the `quest-prompt-rebind.sh` entry from `hooks.UserPromptSubmit`.

### Tuning

After ~50 prompts, run `/quest rebind-stats --days 7`. Look for:
- High `noop` count + low `rebind` → threshold too strict, lower `REBIND_SCORE` in `prompt_rebind_scorer.py`
- False-positive rebinds (you re-claim manually right after) → threshold too lax, raise `REBIND_MARGIN`
- Tune candidates list → these are at the edge, decide which way each should go

### Implementation files

- `~/.claude/skills/quest/prompt_rebind_scorer.py` — IDF tokenizer + two-stage decision + atomic claim rewrite
- `~/.claude/hooks/quest-prompt-rebind.sh` — UserPromptSubmit entry point (~10 lines)
- `~/.claude/skills/quest/test_prompt_rebind.py` — 28-test regression suite (`python3 -m unittest test_prompt_rebind`)
- `~/.claude/quest/log/rebind.jsonl` — append-only observability log (read by `/quest rebind-stats`)

## Tags + Session Binding — UI + CLI + API

Every quest carries an optional freeform `tags[]` array. Tags appear as chips below the quest name on the Quest Log; tags starting with `session:` also render as a 💬 ribbon inside the `.illus` SVG area for high-glance visibility.

### Three ways to manage tags

| From | Action |
|---|---|
| **UI — chip row** | `+ tag` on a card → inline input → `Enter` to commit (accepts comma-separated). `×` on any chip removes. Click a chip body to filter the list by that tag. |
| **UI — `💬 + session`** | Cleaner binding entry. Type just the conversation name; `session:` is auto-prefixed. Page reloads to surface the `.illus` ribbon. |
| **CLI** | `quest tag/bind/unbind/mine` (see Quick reference). |

### JSON API (POST, localhost-only)

```
POST /api/tags/add      {"project":"<p>","id":"<q>","tag":"foo,bar"}
POST /api/tags/remove   {"project":"<p>","id":"<q>","tag":"foo"}
POST /api/tags/bind     {"project":"<p>","id":"<q>","name":"chat-name"}
POST /api/tags/unbind   {"project":"<p>","id":"<q>"}
GET  /api/session       — diagnostic: current server's session_key/label
```

Backed by `~/.claude/skills/quest/server.py` (replaces `python3 -m http.server`). Atomic JSON write under a single writer lock; in-process re-render after each mutation.

### Search bar

Live keyword filter at the top of every Quest Log. Searches name / desc / tags / id / status simultaneously, debounced, persists in `?q=` for shareable URLs. `Esc` or `✕` clears.

### My To-Do editor deeplink

Each plan-card My To-Do section emits an `✎ Edit in editor` button (vscode://file/<abs>) so VS Code / Cursor / Windsurf opens the exact sidecar file. Works for populated and empty-state sidecars.

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

| Section              | Source                            | Icon (pokemon / storybook)                   | When to use                                                                                                                       |
| -------------------- | --------------------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **Your Actions**     | `## Section 14 — Your Actions`    | trainer cap / quill+inkwell                  | Things only the human can do — verify in browser, approve PR, hit a dashboard, pick the next track, leave a deploy alone for soak |
| **Claude's Actions** | `## Section 13 — Post-Validation` | Magnemite-style hovering eye / clockwork eye | Things Claude/the implementation is doing or queued to do — tests, deploys, code changes, undraft PR after soak                   |

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

| Keyword (case-insensitive, free-form)                               | CSS class    | Colour                                             |
| ------------------------------------------------------------------- | ------------ | -------------------------------------------------- |
| `TODO`                                                              | `todo`       | yellow                                             |
| `DONE`, `COMPLETE`, `COMPLETED`                                     | `done`       | green (item title strikethrough + green num badge) |
| `WAITING`, `BLOCKED`                                                | `waiting`    | gray                                               |
| `QUEUED`, `AFTER ...`, `ON ...` (e.g. `AFTER 24H`, `ON GREENLIGHT`) | `queued`     | blue                                               |
| `CONTINUOUS`, `ONGOING`                                             | `continuous` | teal                                               |
| Anything else                                                       | `default`    | neutral                                            |

Display text preserved verbatim — `[AFTER 24H]` shows as "AFTER 24H". Only the colour class is bucketed.

### Inline markdown supported in body

`[label](https://url)` → external link · `` `code` `` → inline code · `**bold**` → strong · `*italic*` → em · single newline → `<br>` · blank line → paragraph break. Anything else is HTML-escaped.

**Fenced code blocks** — a ` ``` ` block in an action body renders as `<pre class="qd-diagram">` (monospace, whitespace + newlines preserved, horizontal-scroll). Use for ASCII diagrams / visual maps inside a §13/§14 action. Both themes (pokemon, storybook) style `.qd-action-body pre.qd-diagram`.

### Legacy `## Section 13/14` checkbox plans

Plans that pre-date this format (using `- [ ]` checkboxes under §13/§14) still parse correctly via fallback — autosync stores them in `tasks[]` / `tasks_user[]` and renders the older collapsible UI. To migrate: delete the checkboxes, replace with `### N. Title [STATUS]` + body. The next autosync swaps the old fields for the new `actions[]` arrays.

## My To-Do — User-Authored Tasks

A per-quest **sidecar file** the operator owns completely — their own todos + notes, separate from the plan-derived task sections (Your Actions / Claude's Actions / Deeds). autosync never plan-parses it; a write only triggers a re-render.

### The sidecar file

`~/.claude/quest/data/notes/<project>__<quest-id>.md` — the `__` separator is collision-proof (ids are kebab slugs, never contain `__`).

```markdown
# My To-Do — <quest name>

- [ ] Ask Yannai about the staging API key
- [x] Renamed the feature branch

## Notes

The soak window ends Friday — don't promote before then.
```

Parse rules: `- [ ]` / `- [x]` lines anywhere → todo items (file order). Content under a `## Notes` heading → the notes block. The `#` header and other prose are ignored. Renders as the **"My To-Do"** section on the plan-card — open by default, green accent, empty-state hint when there's nothing yet.

### CLI — `/quest todo`

`quest.py todo <action> <project> <quest> [args]`:

- `todo add <proj> <quest> "title"` — append `- [ ] title` (creates the file with a header if missing)
- `todo done <proj> <quest> <N>` — flip the Nth checkbox to `[x]` (1-based index)
- `todo undone <proj> <quest> <N>` — flip the Nth checkbox back to `[ ]`
- `todo rm <proj> <quest> <N>` — delete the Nth checkbox line
- `todo note <proj> <quest> "text"` — append a line under `## Notes`
- `todo list <proj> <quest>` — print the file contents + its path
- `todo edit <proj> <quest>` — print the file path (open it in your own editor)

All edits are targeted line edits — free-form content between checkboxes is preserved. Mutating actions re-render; `list`/`edit` don't. `add`/`done`/etc. validate the quest exists first (no orphan files from typos). **Safe autonomous** — no I1 permission gate.

**Stale dashboard after a manual edit**: editing the sidecar through Claude Code's Edit tool auto-re-renders (the autosync hook routes `quest/data/notes/*.md` to a render-only branch). For an external editor, run `/quest render` or any `/quest todo` command.

### NL triggers

- "add todo X to quest Y" / "remind me to X on quest Y" → `/quest todo add`
- "mark my todo N done on X" → `/quest todo done`
- "read quest X's task list / todos / backlog" / "what's on the backlog/roadmap for X" / "what's left on X" / "what do I need to do on X" → **Backlog Read Routine** (below)

### Backlog Read Routine

Read-only — like the Resume Routine, but for "show me the work." Triggered by the NL phrasings above. Steps:

1. **Resolve target** — a quest id / number / name, or a whole project. Same nearest-match resolver as the Resume Routine; fail loud with nearest matches on a miss.
2. **Read** `quests.json` + the My To-Do sidecar file(s).
3. **Present the consolidated picture** — My To-Do (open + done counts, open items), the plan-derived sections (Your Actions / Claude's Actions / Deeds) current state, and `next_step`. For a project-scope ask, repeat for every `current` (and optionally `locked`) quest.
4. **Read-only** — never mutates. Safety Invariant I1 untouched.

## 🧹 Hygiene Cleanup Routine — De-Noise the Roadmap

The map accumulates noise because `autosync` creates a quest on every plan-file write (its `id` = the plan-file slug; before the H1-naming patch its `name` was that codename too). Two failure modes result: (a) a **codename dup-stub** when a hand-named quest already covers the same plan, (b) **shipped work left `current`/`locked`** because the §13 checkboxes were never ticked.

### NL triggers

- "clean up the quests / too many quest cards / which are duplicates / clear the noise" → this routine
- "audit the quests" / "what's actually done but not marked" → this routine

### Step 0 — DETECT (read-only)

```bash
quest hygiene <project>     # one project
quest hygiene               # all projects
```

Reports four buckets: **DUP-RISK** plan collisions (codename stub + real twin on one plan), **MULTI-QUEST** collisions (a plan that intentionally spawns several hand-named sub-quests — NOT noise, never touch), **STUB** quests (0% + empty next_step + missing why/kpi/tasks), **CODENAME** names. Also: `scripts/maintenance/quest_hygiene_audit.py` in a project repo (`--json`, `--strict` gate) is the standalone equivalent.

### The 4 classes + the SAFE action for each

| Class | Signal | Action | Gate |
|---|---|---|---|
| **Shipped-not-done** | `current`/`locked`, but git/ACTIVE.md/live-prod prove it shipped | `quest done <proj> <id>` | Mark done ONLY with **evidence** (commit sha / entry doc / live toggle) — NEVER on name or vibe. `done` won't promote a locked quest while other currents exist. |
| **DUP-RISK dup-stub** | codename stub + real twin share one plan | **merge** any unique `why`/`kpi`/desc/tasks/links the twin LACKS into the twin, THEN remove the stub entry from `quests.json` | **I1 — destructive.** Operator must explicitly authorize. Back up `quests.json` first. Verify no `depends_on` references the stub. |
| **Codename name** (real work) | codename `name`, but live/active | rename `name` → plan **H1 title** (`quest update <proj> <id> --name "<H1>"`). Display-only; keep `id` (URLs/claims/deps stable). | Safe — non-destructive. |
| **Orphan stub** | codename + 0% + no twin | investigate plan + git: shipped → mark done; superseded/abandoned → retire (I1); real-pending → leave or rename | retire = **I1**; leave/rename = safe |

### Hard invariants (what made this safe in practice)

1. **MULTI-QUEST ≠ noise** — a plan that deliberately spawns sub-quests (e.g. a master plan with N tracks) shows as a collision but has zero stubs. Never dedup it.
2. **Evidence before `done`** — a 0% quest is "actually done" only if a commit / entry doc / live prod toggle proves it. Name similarity is not evidence.
3. **Merge before remove** — a dup-stub may carry a `why`/`kpi`/desc the twin lacks. Salvage into the twin first, then delete.
4. **Every removal/retire is I1-gated** — operator explicitly names the project + a destructive verb (remove/retire/delete). Ambient "clean it up" is NOT authorization to delete; it IS enough to mark-done shipped work + rename codenames (both non-destructive).
5. **Renames are display-only** — change `name`, never `id`. The `id` anchors claim files, plan-card URLs, and `depends_on`.
6. **Back up + verify deps** — `cp quests.json quests.json.bak-<ts>` before any removal; confirm no quest's `depends_on` points at a removed id.

### Recurrence prevention (already in place)

- `derive_quest` names new quests from the plan **H1** (not the codename) — fewer codename names going forward.
- The `knowledge-quest-hygiene` weekly routine (OGAS Routines Platform) re-flags DUP-RISK + codename counts so noise self-surfaces.
- **Best fix is upstream**: name the plan FILE to match the intended quest `id` so autosync UPDATES the right quest instead of spawning a twin (Safety Invariant I2).

### Forbidden during this routine

- DON'T dedup a MULTI-QUEST collision.
- DON'T mark a quest `done` without shipped-evidence.
- DON'T remove/retire anything without explicit I1 authorization.
- DON'T rename a quest's `id` (only `name`).
- DON'T run `quest reset --chapter` to "clean up" — it archives ALL done+current (sparing only locked) and will nuke in-flight work. This routine is surgical; chapter-reset is not.

## ✨ Name Cleanup Routine — Short Thematic Names, Goal Lives in `desc`

Sibling to the Hygiene routine, but about NAME QUALITY, not dup-stubs. The map fills with ugly machine names: bare `Entry NNN <titlecased slug>` auto-stubs and whimsical plan-mode codenames (`We Have Create Tthe Fizzy Dove`). This routine fixes the display `name` only.

### NL triggers
- "clean up quest names / fix the codename quests / the names are ugly / make the quest names readable" → this routine

### Philosophy (operator-set, OGAS 2026-06-02)
- **`name` = SHORT thematic label** (≤ ~5 words, human-readable). It's the card TITLE. Operator's loved examples: "Analytics Agent Platform", "Web Generation", "Nova Marketplace Landing".
- **goal/mission lives in `desc`** — the dashboard ALREADY renders `desc` as the card subtitle. Never cram the goal/mission into the name (no long sentences as names).
- **`id` is immutable** — it anchors plan-card URLs, session claims (`/quest claim`), and `depends_on`. NEVER change it. Only `name` changes (display-only, reversible).
- A name is **bad** only when it's a machine artifact: a bare `Entry NNN <slug>` stub, OR a whimsical codename whose slug == the id. Names that already read as a goal/theme (have a `—`/`:`/`#NNN` separator + length) are LEFT ALONE.
- The short NAME itself is **human/Claude judgment** — the script's auto-suggestions are a STARTING POINT, edit them to the operator's style.

### The 4-step routine (engine: `~/.claude/skills/quest/name_cleanup.py`)
```bash
# 1. SCAN — detect flagged quests + best-effort short-name suggestions -> proposals JSON + table
python3 ~/.claude/skills/quest/name_cleanup.py scan --project <proj>
#    -> writes ~/.claude/quest/run/name-cleanup-proposals.json
# 2. EDIT the proposals JSON — make each `suggested` a SHORT thematic name (your style)
# 3. HTML PREVIEW — before/after rendered as name + goal-subtitle; operator EYEBALLS (visual-first gate)
python3 ~/.claude/skills/quest/name_cleanup.py html --project <proj> --port 8788
setsid python3 -m http.server 8788 --directory /tmp/claude/quest-name-cleanup >/dev/null 2>&1 &
#    -> http://localhost:8788/   (operator confirms before apply)
# 4. APPLY — name-only updates via quest.py (id + desc untouched), auto-re-renders
python3 ~/.claude/skills/quest/name_cleanup.py apply --project <proj> --in ~/.claude/quest/run/name-cleanup-proposals.json
```

### Hard invariants
1. **`name` only** — never touch `id` or `desc`. The goal stays in `desc` (the subtitle).
2. **Visual-eyeball gate before apply** — always serve the HTML before/after and get the operator's OK (`.claude/rules/visual-diff-first.md`). `apply` is reversible (set `name` back) but the eyeball is the gate.
3. **Don't expand good names** — if a name already reads as a goal/theme, leave it. Over-flagging good short names ("Web Generation") was the original mistake.
4. **Suggestions are drafts** — `scan` proposes mechanically; the SHORT thematic name is operator/Claude judgment. Edit the JSON before `apply`.
5. **`apply` skips unedited placeholders** (`(EDIT ME …)` / `(ASK …)`) — so a half-edited proposals file is safe.

### Going forward
Create new quests with a short thematic `name` + the 1-sentence goal in `desc`. The autosync default still pulls the plan H1 (often long) — when it produces a long/codename name, run this routine.

## 🗺️ Master Quest View — the CANONICAL presentation (route map + quest-log + picker)

For roadmaps with many quests (OGAS had 36 active / 135 total), a flat card grid is spam. The **master view** groups every quest under a handful of **master plans** (epics). **This is the default, source-of-truth presentation for every project that defines `epics` + `master_view_enabled`** — it governs all THREE dashboard surfaces, not just the quest log. Origin: OGAS 2026-06-02 (operator: "only main quests, click → popup with sub-quests"; extended to the route map + picker + project routing the same day). Worldmap-tuned today; other themes opt in later.

### The 3 master surfaces (all driven off `epics`)

| Surface | What master-view does | Click target |
|---|---|---|
| **route.html** (overworld map) | Road landmarks ARE the epics — one clean pin per master (≤9 slots, short names → no label overlap), each with a sub-quest **count badge** + rolled-up progress + derived status. Replaces the old `n`-keyed pins that collided and surfaced stale #1..#9 quests as "mains". | pin → `quest-log.html#epic-<id>` (auto-opens that master's popup) |
| **quest-log.html** (master board) | Opens to the master cards (default-visible); `Master quests \| All quests` switch; any filter/search drops to the flat grid. | card → popup of its sub-quests → `plan-card.html?q=<id>` |
| **plan-card.html** (active-picker bar) | The top picker collapses to the MASTER quests — one entry per epic with active work (`<name> (<active-count>)`) — instead of listing every current quest. | entry → that master's lead current sub-quest |

**Project routing**: `http://localhost:8770/<project>/` serves that project's **`route.html`** (the overworld map) for every project; root `/` still serves the global Trainer-Hall index (`server.py::do_GET` rewrite).

**Progress-bar gotcha (canonical)**: every popup/grid progress-FILL element MUST be `display:block`. An inline `<span>` fill ignores `width`/`height`, so 0% and 100% render identically (empty). Caught OGAS 2026-06-02 — the popup bars looked dead until `.qm-fill`/`.sq-fill` got `display:block`.

### Data model (per project, in `quests.json`)
```jsonc
"projects": { "<id>": {
  "master_view_enabled": true,           // gate (reversible)
  "epics": [
    { "id": "beacon", "name": "Beacon Pilot", "landmark": "tower",
      "tagline": "Org page → 3 variations → leads + agent + analytics" }
    // ... one per master plan
  ],
  "quests": [ { "id": "...", "epic": "beacon", ... } ]   // each quest tags its master
}}
```
- **`epics[]`** = master metadata: `id` · `name` (short thematic) · `landmark` (theme drawing: house/tower/mill/bridge/camp/cave/castle) · `tagline` (1 line, shown under the name + in the popup head).
- **`epic`** on each quest = its master's id. Membership is derived from this field; rollup % = mean of a master's members; "in flight" = members with 0<progress<1.
- A quest with no `epic` simply won't appear in the master grid (still in the flat list).

### Renderer (additive + reversible)
- **quest-log board** — `master_view.py::render_master_log(pid, project, site_dir)` **injects** the master board into the freshly-rendered `quest-log.html` — it does NOT replace the page. Kept verbatim: header, XP bar, Active/Visited/Sealed, Show-All/Active-Only/All, search, the full flat card grid + all its JS. Added: a `Master quests | All quests` switch, the master-card grid (default-visible), and a click-popup per master (sub-quests → `plan-card.html?q=<id>`, clickable). Any filter/search interaction drops to the flat list; "Master quests" switches back. Each modal carries `data-epic="<id>"` + an on-load hash reader so `quest-log.html#epic-<id>` auto-opens that popup (the route-map deep-link target). `render.py` calls it as a **lazy try/except post-step** — can never break the core render. Also writes a `master-log.html` alias.
- **route map** — `render.py::_epic_route_mains(project, theme)` builds one synthetic main-pin per epic and is applied **only to the route view's scope** (never mutates the shared project, so quest-log/plan-card are untouched). Returns `[]` (→ legacy `n`-keyed pins) unless `master_view_enabled` + `epics`.
- **active-picker** — `render.py::_render_quest_blocks` builds the picker from epics-with-active-work when `master_view_enabled` + `epics`; else the legacy "list every current quest" bar.
- **project routing** — `server.py::do_GET` rewrites `/<project>/` → `/<project>/route.html` when that file exists; root `/` untouched.

### Reversibility (all tested) — every surface falls back cleanly
1. Per-project: `master_view_enabled: false` → `/quest render` → quest-log reverts to flat, route map reverts to legacy `n`-keyed pins, picker reverts to the full current-quest list.
2. Global kill switch: `touch ~/.claude/quest/master-view-disabled` → render → all projects flat (no data change). (Note: kills the quest-log board; the route/picker also no-op without `epics`.)
3. Code: `git checkout render.py master_view.py server.py themes/worldmap/route.html.tmpl`. The flat grid lives INSIDE the injected page, so nothing is ever lost.
- A project **without** `epics`/`master_view_enabled` is unaffected by all of the above — it gets the legacy flat quest-log, `n`-keyed route pins, and full-current-list picker.

### Add it to a project
1. Add `epics[]` + set `epic` on each quest (group by theme; names short, taglines 1-line) + `master_view_enabled: true`.
2. `/quest render`. All three surfaces light up at once: the route map shows one clean landmark per epic, the quest-log opens to the master board, and the plan-card picker collapses to masters. `localhost:8770/<project>/` opens the route map.
- **Curate epics by eyeball** (like the OGAS rollout) — don't auto-group blindly; bad groupings read worse than flat. Best for large roadmaps (15+ active); small projects (<~10 active) are fine flat.
- **`epic` is set in `quests.json` directly** (not a CLI flag) — it's the one quest field edited by hand. Keep epic `name`s short (they become route-map labels — long names re-introduce overlap).

## Icon system — modular UI components

Every section-marker glyph on the dashboard resolves through a partial: `{{> icons/<name>}}`. Themes can override per-icon by placing their own version at `themes/<theme>/icons/<name>.html.tmpl`; missing overrides fall back to `themes/_shared/icons/<name>.html.tmpl`. Icons use inline SVG; default styles use `currentColor` so CSS can recolour them.

Built-in icon registry:

| Name        | Used for                                                     | Pokemon look                 | Storybook look               |
| ----------- | ------------------------------------------------------------ | ---------------------------- | ---------------------------- |
| `user`      | Your Actions section header                                  | Trainer cap with pokeball    | Quill + inkwell              |
| `robot`     | Claude's Actions section header                              | Magnemite-style hovering eye | Clockwork brass eye          |
| `active`    | "Active" status, home-index crest, currently-battling marker | Crossed swords               | Wax seal with heraldic mark  |
| `visited`   | "Visited" filter button                                      | 5-point star                 | Illuminated 8-point star     |
| `sealed`    | "Sealed" filter button                                       | Padlock                      | Brass key + lock plate       |
| `branch`    | Pill — git branch                                            | shared default fork          | shared default fork          |
| `kpi`       | Pill — KPI target                                            | shared default bar chart     | shared default bar chart     |
| `tags`      | Pill — quest tags                                            | shared default tag           | shared default tag           |
| `plan-file` | "Plan file" / "Charter" footer                               | shared default scroll        | shared default scroll        |
| `why`       | Marker on the "why" motivation line                          | shared default 8-point spark | shared default 8-point spark |

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

| Tag                                | URL it opens                                                                    |
| ---------------------------------- | ------------------------------------------------------------------------------- |
| `quest:ogas/layout-editor-entry-…` | `http://localhost:8770/ogas/plan-card.html?q=layout-editor-entry-435-soak-ship` |
| `quest:ogas/-` (no current quest)  | `http://localhost:8770/ogas/`                                                   |
| `quest:-` (no project from cwd)    | `http://localhost:8770/`                                                        |

### Recommended SessionEnd hook (auto-unclaim)

Add to `~/.claude/settings.json` if you want claims to clear automatically when a session ends:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/quest/quest.py unclaim 2>/dev/null || true"
          }
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

| File                                    | Purpose                                        |
| --------------------------------------- | ---------------------------------------------- |
| `~/.claude/scripts/statusline-quest.sh` | Bash helper — `quest_indicator <cwd>` function |
| `~/.claude/scripts/statusline.sh`       | Sources helper, appends `quest:<tag>` field    |
| `~/.claude/skills/quest/quest.py`       | `cmd_claim`, `cmd_unclaim`, `cmd_claimed`      |
| `~/.claude/quest/run/session-*.quest`   | Per-session claim files (gitignored)           |

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
      "xp": { "current": 50, "max": 100 },
      "quests": [
        {
          "id": "build-login",
          "n": 1,
          "name": "Login Tower",
          "desc": "OAuth flow with email + Google",
          "landmark": "tower",
          "status": "current",
          "progress": 0.6,
          "xp_reward": 25,
          "plan": "apollo-login.md",
          "next_step": "Wire OAuth callback",

          "tasks": [
            { "title": "Pick OAuth library", "done": true },
            { "title": "Wire callback handler", "done": false }
          ],
          "last_touched": "2026-05-07T14:23:00Z",
          "branch": "feat/login",
          "last_commit": {
            "sha": "abc1234",
            "msg": "wip: oauth",
            "date": "2026-05-07T..."
          },
          "why": "Login is the gate to everything else; ship it first.",
          "blockers": [],
          "tags": ["auth", "core"],
          "kpi": "login success rate >99%",
          "depends_on": [],
          "links": [
            {
              "url": "https://example.com",
              "label": "Display name",
              "desc": "Optional one-line description"
            }
          ],
          "effort": { "estimate_hr": 4, "actual_hr": 2 }
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
{ "path_map": [{ "path": "/home/me/myproject", "id": "myproject" }] }
```

## Troubleshooting

| Symptom                              | First check                                                                 |
| ------------------------------------ | --------------------------------------------------------------------------- |
| Quest didn't appear after plan write | `tail -50 ~/.claude/quest/logs/autosync.log`                                |
| Dashboard URL doesn't load           | `systemctl --user status quest-dashboard`                                   |
| HTML looks wrong / partial missing   | `python3 ~/.claude/skills/quest/render.py --dry-run`                        |
| Wrong project chosen by hook         | autosync log includes resolution trace; check `~/.claude/quest/config.json` |
| Theme not picking up                 | `python3 ~/.claude/skills/quest/quest.py status` lists discovered themes    |

## Source of truth

- Skill: `~/.claude/skills/quest/`
- Data: `~/.claude/quest/data/quests.json` (versioned)
- Config: `~/.claude/quest/config.json` (path map; NOT versioned in public engine)
- Site: `~/.claude/quest/site/` (gitignored, regeneratable)
- Logs: `~/.claude/quest/logs/` (gitignored)
- Hook: `~/.claude/hooks/quest-plan-autosync.sh`
