# Data Schema (v2)

`~/.claude/quest/data/quests.json` is the single source of truth.

## Top-level

```json
{
  "version": 2,
  "schema_doc": "...",
  "level_threshold": 100,
  "xp_per_quest": 25,
  "projects": { "<id>": <Project> }
}
```

## Project

| Field | Type | Notes |
|---|---|---|
| `name` | string | Display name |
| `subtitle` | string | One-line tagline |
| `theme` | string | Must match a directory in `themes/` |
| `level` | int | Computed as `floor(xp_done / 100) + 1` (cosmetic) |
| `xp` | `{current, max}` | XP toward next level |
| `quests` | `Quest[]` | Quest list; `n` field controls map position |

## Quest (v2)

### Core (always present)

| Field | Type |
|---|---|
| `id` | string slug (unique within project) |
| `n` | int (1..N, drives map position via theme.json `positions`) |
| `name` | string (display) |
| `desc` | string (1 line) |
| `landmark` | one of `house`, `tower`, `mill`, `bridge`, `camp`, `cave`, `castle` |
| `status` | `done` \| `current` \| `locked` |
| `progress` | float 0.0-1.0 |
| `xp_reward` | int (default 25) |
| `plan` | string (filename, used by autosync to match) |
| `next_step` | string (shown when status=current) |

### v2 fields (all optional, render only if present)

| Field | Type | Source |
|---|---|---|
| `tasks` | `[{title: string, done: bool}]` | Auto-parsed from `## Section 13` checkboxes |
| `last_touched` | ISO8601 string | Auto-bumped on every parser run |
| `branch` | string | `git branch --show-current` from plan's repo |
| `last_commit` | `{sha, msg, date}` | `git log -1` from plan's repo |
| `why` | string | Hand-set — 1 sentence motivation |
| `blockers` | string[] | Hand-set |
| `tags` | string[] | Hand-set |
| `kpi` | string | Hand-set — KPI definition (free-form) |
| `depends_on` | string[] | Hand-set — quest IDs that must be done first |
| `links` | `[{project, quest}]` | Hand-set — cross-project relations |
| `effort` | `{estimate_hr, actual_hr}` | Hand-set |

## Auto-parser behavior

`autosync.py` scans plan content and updates these fields:

1. `tasks` — checkboxes in `## Section 13 — Post-Validation`, falls back to all checkboxes
2. `progress` — `done_count / total_count` from those checkboxes
3. `last_touched` — current UTC ISO8601 on every run
4. `branch` + `last_commit` — pulled from git if plan path is in a repo

Fields the parser **never touches**: `name`, `desc`, `landmark`, `status`, `xp_reward`, `next_step`, `why`, `blockers`, `tags`, `kpi`, `depends_on`, `links`, `effort`. Hand-set values are preserved.

## Backward compat (v1 → v2)

v1 is forward-compatible — quests without v2 fields render fine, all `{{#if}}` blocks just don't show. To upgrade: bump `version: 2` and add fields incrementally.
