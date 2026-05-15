#!/usr/bin/env python3
"""quest CLI — manage projects and quests in the central quests.json.

Subcommands: init, add, update, done, theme, render, status

Usage examples:
  quest.py status
  quest.py init <project_id> --name "Display Name" --subtitle "..." --theme pokemon
  quest.py add <project_id> "Quest Name" --landmark camp --plan myplan.md
  quest.py update <project_id> <quest_id> --progress 0.7 --next "do the thing"
  quest.py done <project_id> <quest_id>
  quest.py theme <project_id> <theme_name>
  quest.py render
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import sidecar

ROOT = Path.home() / ".claude"
DATA = ROOT / "quest" / "data" / "quests.json"
THEMES = ROOT / "skills" / "quest" / "themes"
RENDER = ROOT / "skills" / "quest" / "render.py"
RUN = ROOT / "quest" / "run"  # Per-session claim files live here
CONFIG = ROOT / "quest" / "config.json"
DASHBOARD_URL = "http://localhost:8770"


# ---- Session identity (claim/unclaim) ----
#
# Each CC session is identified by walking up the process tree until we hit
# a process whose comm == "claude". Its (pid, raw starttime ticks) form a
# stable, deterministic key for the lifetime of that CC instance.
#
# Why not bus identity? The inter-agent registry has stale entries for sessions
# whose SessionStart hook didn't register (or whose claude_pid rolled). Walking
# /proc directly is more robust + dependency-free.
def _walk_to_claude() -> tuple[int, str] | None:
    """Walk up parent processes from CURRENT pid; return (claude_pid, raw_ticks)
    for the first ancestor whose /proc/<pid>/comm == "claude". Raw ticks come
    from /proc/<pid>/stat field 22 — set at fork, never changes (deterministic
    fingerprint). Returns None on Linux/proc unavailability."""
    import os as _os
    pid = _os.getpid()
    for _ in range(40):  # generous walk depth — hook chains can be 7-20 deep
        if pid <= 1:
            return None
        try:
            comm = (Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip())
        except OSError:
            return None
        if comm == "claude":
            try:
                stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            except OSError:
                return None
            # Strip the comm parens (it can contain spaces) before splitting.
            stat_clean = re.sub(r"\([^)]*\)", "X", stat, count=1)
            fields = stat_clean.split()
            if len(fields) >= 22:
                return (pid, fields[21])
            return None
        # Read ppid from stat field 4 (after stripping comm parens)
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except OSError:
            return None
        stat_clean = re.sub(r"\([^)]*\)", "X", stat, count=1)
        fields = stat_clean.split()
        if len(fields) < 4:
            return None
        try:
            pid = int(fields[3])
        except ValueError:
            return None
    return None


def session_key() -> str | None:
    """Stable session identifier: '<claude_pid>-<starttime_ticks>'. None on failure."""
    info = _walk_to_claude()
    if not info:
        return None
    return f"{info[0]}-{info[1]}"


def claim_file_for(key: str) -> Path:
    return RUN / f"session-{key}.quest"


def _gc_dead_session_claims() -> int:
    """Remove session-<key>.quest files whose underlying claude process is gone.

    Walks RUN dir, parses each session-<pid>-<ticks>.quest, verifies:
      - /proc/<pid>/comm reads as "claude" (process exists + is claude)
      - /proc/<pid>/stat field 22 (starttime ticks) matches the claimed ticks
        (catches PID reuse: a different claude proc reusing the same PID has
        different starttime ticks).

    Either check failing → the claim is dead, delete the file. Best-effort;
    individual delete failures are swallowed. Returns count removed.

    Called opportunistically from cmd_claim / cmd_status / cmd_render — keeps
    the run/ dir tidy without needing a cron. Idempotent + cheap (one
    /proc read per file).

    Evidence: 2026-05-15 — 6 stale claim files accumulated in ~/.claude/quest/run/
    pointing to dead CC sessions; no eviction mechanism existed before this.
    """
    if not RUN.exists():
        return 0
    removed = 0
    for f in RUN.glob("session-*.quest"):
        m = re.match(r"session-(\d+)-(\d+)\.quest$", f.name)
        if not m:
            continue
        pid, ticks_claimed = int(m.group(1)), m.group(2)
        is_dead = False
        try:
            comm = Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
            if comm != "claude":
                is_dead = True
            else:
                stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
                stat_clean = re.sub(r"\([^)]*\)", "X", stat, count=1)
                fields = stat_clean.split()
                if len(fields) < 22 or fields[21] != ticks_claimed:
                    is_dead = True
        except (OSError, IndexError, ValueError):
            is_dead = True
        if is_dead:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed


LANDMARKS = ["house", "tower", "mill", "bridge", "camp", "cave", "castle"]


# ---- IO ----

def load() -> dict:
    if not DATA.exists():
        DATA.parent.mkdir(parents=True, exist_ok=True)
        return {"version": 1, "level_threshold": 100, "xp_per_quest": 25, "projects": {}}
    return json.loads(DATA.read_text(encoding="utf-8"))


def save(data: dict) -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def list_themes() -> list:
    if not THEMES.exists():
        return []
    return sorted(d.name for d in THEMES.iterdir() if (d / "theme.json").exists())


def slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "quest"


def render_now() -> int:
    proc = subprocess.run(["python3", str(RENDER)], capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"render.py failed:\n{proc.stderr}", file=sys.stderr)
    else:
        sys.stdout.write(proc.stdout)
    return proc.returncode


def recompute_level(project: dict, threshold: int = 100, xp_per_quest: int = 25) -> None:
    """Recompute level + per-level xp from done count."""
    done = sum(1 for q in project.get("quests", []) if q.get("status") == "done")
    total_xp = done * xp_per_quest
    project["level"] = (total_xp // threshold) + 1
    project["xp"] = {"current": total_xp % threshold, "max": threshold}


def get_project(data: dict, pid: str) -> dict:
    if pid not in data["projects"]:
        sys.exit(f"ERROR: project '{pid}' not found. Known: {list(data['projects'].keys())}")
    return data["projects"][pid]


def find_quest(project: dict, qid: str) -> dict:
    for q in project["quests"]:
        if q["id"] == qid:
            return q
    sys.exit(f"ERROR: quest '{qid}' not found in {project.get('name', '?')}")


# ---- subcommands ----

def cmd_status(args) -> int:
    # Opportunistic GC: cmd_status is the most-called read endpoint. Sweep dead
    # session claim files on every invocation. Best-effort + silent on noise.
    try:
        _gc_dead_session_claims()
    except Exception:
        pass
    data = load()
    themes = list_themes()
    print(f"Dashboard: {DASHBOARD_URL}")
    print(f"Data:      {DATA}")
    print(f"Themes:    {', '.join(themes) if themes else '(none discovered)'}")
    print(f"Threshold: {data.get('level_threshold', 100)} XP/level · {data.get('xp_per_quest', 25)} XP/quest")
    print()
    print("Projects:")
    for pid, p in data["projects"].items():
        cnts = {"done": 0, "current": 0, "locked": 0}
        for q in p["quests"]:
            cnts[q.get("status", "locked")] = cnts.get(q.get("status", "locked"), 0) + 1
        active = next((q for q in p["quests"] if q.get("status") == "current"), None)
        active_str = f" — current: {active['name']} ({int(100*active.get('progress',0))}%)" if active else ""
        print(f"  {pid:8s} [{p.get('theme'):9s}] Lv {p.get('level',1)} ({p['xp']['current']}/{p['xp']['max']} XP) — "
              f"{cnts['done']} done, {cnts['current']} active, {cnts['locked']} locked{active_str}")
    return 0


def cmd_init(args) -> int:
    data = load()
    if args.project_id in data["projects"] and not args.force:
        sys.exit(f"ERROR: project '{args.project_id}' already exists. Use --force to overwrite.")
    if args.theme not in list_themes():
        sys.exit(f"ERROR: theme '{args.theme}' not found. Available: {list_themes()}")
    data["projects"][args.project_id] = {
        "name": args.name or args.project_id.title(),
        "subtitle": args.subtitle or "",
        "theme": args.theme,
        "level": 1,
        "xp": {"current": 0, "max": data.get("level_threshold", 100)},
        "quests": [],
    }
    save(data)
    print(f"Initialized project '{args.project_id}' with theme '{args.theme}'")
    return render_now()


def cmd_add(args) -> int:
    data = load()
    project = get_project(data, args.project_id)
    qid = args.id or slug(args.name)
    if any(q["id"] == qid for q in project["quests"]):
        sys.exit(f"ERROR: quest id '{qid}' already exists in '{args.project_id}'")
    n = len(project["quests"]) + 1
    landmark = args.landmark or LANDMARKS[(n - 1) % len(LANDMARKS)]
    # I1: "current" is plural — never auto-lock based on existing currents.
    # New quests default to current; operator must pass --locked to gate them.
    # Regression: ~/.claude/skills/quest/test_current_is_plural.py (8 tests)
    status = "locked" if args.locked else "current"
    quest = {
        "id": qid,
        "n": n,
        "name": args.name,
        "desc": args.desc or "",
        "landmark": landmark,
        "status": status,
        "progress": 0.0,
        "xp_reward": args.xp or data.get("xp_per_quest", 25),
        "plan": args.plan or "",
        "next_step": args.next or "",
    }
    project["quests"].append(quest)
    save(data)
    print(f"Added: {args.project_id}/{qid} (#{n}, {landmark}, {status})")

    # Auto-claim THIS session for the newly-added quest — prevents stale-claim
    # drift where a long-running CC session keeps an old claim while the
    # operator pivots to a new work topic. Opt out with --no-claim or
    # env QUEST_AUTO_CLAIM_ON_ADD=0.
    # Evidence: 2026-05-14 OGAS — session bound to entry-460 for 2 days while
    # actually working on dorian-investors-landing; statusline showed the wrong
    # quest, operator only caught it by glancing at the card URL.
    try:
        no_claim = getattr(args, "no_claim", False) or \
                   os.environ.get("QUEST_AUTO_CLAIM_ON_ADD", "1") == "0"
        if not no_claim:
            key = session_key()
            if key:
                RUN.mkdir(parents=True, exist_ok=True)
                claim_file_for(key).write_text(
                    f"{args.project_id}/{qid}\n", encoding="utf-8"
                )
                print(f"Claimed: {args.project_id}/{qid} (session auto-rebind)")
    except Exception:
        pass  # best-effort — never break add on claim-write failure

    return render_now()


def cmd_update(args) -> int:
    data = load()
    project = get_project(data, args.project_id)
    quest = find_quest(project, args.quest_id)
    changes = []
    if args.progress is not None:
        quest["progress"] = max(0.0, min(1.0, args.progress))
        changes.append(f"progress={quest['progress']}")
    if args.next is not None:
        quest["next_step"] = args.next
        changes.append("next_step")
    if args.name is not None:
        quest["name"] = args.name
        changes.append("name")
    if args.desc is not None:
        quest["desc"] = args.desc
        changes.append("desc")
    if getattr(args, "problem", None) is not None:
        quest["problem"] = args.problem
        changes.append("problem")
    if getattr(args, "solution", None) is not None:
        quest["solution"] = args.solution
        changes.append("solution")
    if args.landmark is not None:
        if args.landmark not in LANDMARKS:
            sys.exit(f"ERROR: landmark must be one of {LANDMARKS}")
        quest["landmark"] = args.landmark
        changes.append(f"landmark={args.landmark}")
    if args.status is not None:
        if args.status not in ("done", "current", "locked"):
            sys.exit("ERROR: status must be done|current|locked")
        # I1: "current" is plural — promoting one quest MUST NOT demote others.
        # Only operator-explicit `update <id> --status locked` can demote a quest.
        # Regression: ~/.claude/skills/quest/test_current_is_plural.py (8 tests)
        quest["status"] = args.status
        changes.append(f"status={args.status}")
    if getattr(args, "clear_links", False):
        quest["links"] = []
        changes.append("links=cleared")
    if getattr(args, "add_link", None):
        quest.setdefault("links", [])
        for spec in args.add_link:
            parts = spec.split("|", 2)
            url = parts[0].strip()
            if not url:
                sys.exit("ERROR: --add-link requires a URL (got empty string before |)")
            label = parts[1].strip() if len(parts) > 1 and parts[1].strip() else url
            desc = parts[2].strip() if len(parts) > 2 else ""
            quest["links"].append({"url": url, "label": label, "desc": desc})
        changes.append(f"links+={len(args.add_link)}")
    save(data)
    print(f"Updated {args.project_id}/{args.quest_id}: {', '.join(changes) if changes else '(no changes)'}")

    # Auto-claim THIS session when the quest is being SET to current — mirror
    # of cmd_add's auto-claim. Closes the gap where /quest update X --status
    # current would NOT update the claim file, leaving the statusline stuck on
    # whatever the old claim pointed to (the 2026-05-14 entry-460 / 2026-05-15
    # moshytz-variant-engine recurrence both hit this). Opt out with
    # env QUEST_AUTO_CLAIM_ON_UPDATE=0.
    try:
        if args.status == "current":
            no_claim = os.environ.get("QUEST_AUTO_CLAIM_ON_UPDATE", "1") == "0"
            if not no_claim:
                key = session_key()
                if key:
                    RUN.mkdir(parents=True, exist_ok=True)
                    claim_file_for(key).write_text(
                        f"{args.project_id}/{args.quest_id}\n", encoding="utf-8"
                    )
                    print(f"Claimed: {args.project_id}/{args.quest_id} (session auto-rebind)")
    except Exception:
        pass  # best-effort — never break update on claim-write failure

    return render_now()


def cmd_done(args) -> int:
    data = load()
    project = get_project(data, args.project_id)
    quest = find_quest(project, args.quest_id)
    if quest.get("status") == "done":
        print(f"Already done: {args.quest_id}")
        return 0
    quest["status"] = "done"
    quest["progress"] = 1.0
    quest["next_step"] = ""
    # Promote next locked to current if no other current exists
    has_current = any(q.get("status") == "current" for q in project["quests"])
    if not has_current:
        for q in project["quests"]:
            if q.get("status") == "locked":
                q["status"] = "current"
                break
    recompute_level(project, data.get("level_threshold", 100), data.get("xp_per_quest", 25))
    save(data)
    print(f"Quest done: {project['name']} / {quest['name']}")
    print(f"  +{quest.get('xp_reward', 25)} XP · Lv {project['level']} · {project['xp']['current']}/{project['xp']['max']}")
    return render_now()


def cmd_theme(args) -> int:
    data = load()
    project = get_project(data, args.project_id)
    if args.theme_name not in list_themes():
        sys.exit(f"ERROR: theme '{args.theme_name}' not found. Available: {list_themes()}")
    old = project.get("theme")
    project["theme"] = args.theme_name
    save(data)
    print(f"{args.project_id}: theme {old} → {args.theme_name}")
    return render_now()


def cmd_style(args) -> int:
    """Set the home-index card accent color and/or landmark icon for a project.

    Both fields are optional — pass --accent or --icon (or both). Render.py
    falls back to per-pid defaults when not set, so unset === default look.
    Accent must be a 6-digit hex like #ff6a3a; icon must match a landmark in
    the project's theme directory (house/camp/castle/cave/tower/bridge/mill).
    """
    data = load()
    project = get_project(data, args.project_id)
    changes = []
    if args.accent is not None:
        accent = args.accent.strip()
        if accent and not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
            sys.exit(f"ERROR: accent must be a 6-digit hex like #ff6a3a (got '{accent}')")
        old = project.get("accent")
        if accent:
            project["accent"] = accent
            changes.append(f"accent {old or '(default)'} → {accent}")
        else:
            project.pop("accent", None)
            changes.append(f"accent {old or '(default)'} → (default)")
    if args.icon is not None:
        icon = args.icon.strip()
        if icon and icon not in LANDMARKS:
            sys.exit(f"ERROR: icon must be one of {LANDMARKS} (got '{icon}')")
        old = project.get("icon")
        if icon:
            project["icon"] = icon
            changes.append(f"icon {old or '(default)'} → {icon}")
        else:
            project.pop("icon", None)
            changes.append(f"icon {old or '(default)'} → (default)")
    if not changes:
        print("No changes — pass --accent #hex and/or --icon name")
        return 0
    save(data)
    print(f"{args.project_id}: {' · '.join(changes)}")
    return render_now()


def cmd_render(args) -> int:
    return render_now()


def cmd_reset(args) -> int:
    """Archive current+done quests into chapters[<name>], optionally clear locked.

    Mental model: closing a chapter and starting a new map. Done/active quests
    become 'past adventures'. Locked quests survive by default (so the next
    backlog moves forward). Pass --clean to wipe locked too.

    Level/xp reset to baseline. Chapters are append-only — re-using the same
    chapter name appends new entries to the existing array.

    SAFETY GATE: defaults to preview-only. Pass --yes to actually mutate. This
    prevents accidental NL-triggered resets ('we wrapped that up' said in
    passing should not nuke 14 quests)."""
    data = load()
    project = get_project(data, args.project_id)

    # Validate chapter name
    chap = (args.chapter or "").strip()
    if not chap:
        sys.exit("ERROR: --chapter <name> is required (e.g. 'q2-2026-bundle-a')")
    chap_slug = slug(chap)

    quests = project.get("quests", [])
    if not quests:
        sys.exit(f"ERROR: project '{args.project_id}' has no quests to archive")

    # Partition
    archived = []
    surviving = []
    for q in quests:
        st = q.get("status", "locked")
        if st in ("done", "current"):
            archived.append(q)
        elif st == "locked" and not args.clean:
            surviving.append(q)
        else:  # locked + --clean → archive these too
            archived.append(q)

    # Preview without --yes — show what WOULD happen and exit.
    if not args.yes:
        print(f"PREVIEW (no changes made — pass --yes to commit):")
        print(f"  project: {args.project_id}")
        print(f"  chapter: '{chap_slug}'")
        print(f"  archive ({len(archived)}):")
        for q in archived:
            tag = q.get("status", "?")
            print(f"    [{tag:7s}] #{q.get('n','?'):>2} {q.get('name','?')}")
        print(f"  survive ({len(surviving)}):")
        for q in surviving:
            print(f"    [{q.get('status','?'):7s}] #{q.get('n','?'):>2} {q.get('name','?')}")
        if surviving:
            print(f"  level/xp reset to baseline · '{surviving[0].get('name','?')}' will be promoted to current")
        else:
            print(f"  level/xp reset to baseline · NO surviving quests (project will be empty until next /quest add)")
        if args.clean:
            print(f"  --clean: locked quests are also archived")
        print(f"\nTo commit: rerun with --yes")
        return 0

    if not archived and not surviving:
        sys.exit("ERROR: partition produced 0 quests on both sides — nothing to do")

    chapters = project.setdefault("chapters", {})
    existing = chapters.setdefault(chap_slug, [])

    # Assign archive metadata + append
    import datetime as dt
    archived_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for q in archived:
        q["archived_at"] = archived_at
        # Drop interactive fields that no longer matter in a frozen chapter
        q.pop("next_step", None)
        existing.append(q)

    # Renumber surviving (now n=1, 2, ...) — keep order
    for i, q in enumerate(surviving, start=1):
        q["n"] = i
    # Promote first surviving locked → current if any survive
    promoted = ""
    if surviving:
        any_current = any(q.get("status") == "current" for q in surviving)
        if not any_current:
            surviving[0]["status"] = "current"
            promoted = surviving[0].get("name", "")

    project["quests"] = surviving
    # Reset level/xp baseline
    threshold = data.get("level_threshold", 100)
    project["level"] = 1
    project["xp"] = {"current": 0, "max": threshold}

    save(data)
    archived_count = len(archived)
    surviving_count = len(surviving)
    print(f"Reset {args.project_id}: chapter '{chap_slug}' (+{archived_count} archived) · {surviving_count} surviving quest(s)")
    if promoted:
        print(f"  Promoted to current: {promoted}")
    return render_now()


def cmd_chapters(args) -> int:
    """List archived chapters for a project (or all)."""
    data = load()
    if args.project_id:
        ps = {args.project_id: get_project(data, args.project_id)}
    else:
        ps = data["projects"]
    for pid, project in ps.items():
        chapters = project.get("chapters") or {}
        if not chapters:
            print(f"  {pid}: (no chapters yet)")
            continue
        print(f"  {pid}:")
        for name, qs in chapters.items():
            done = sum(1 for q in qs if q.get("status") == "done")
            print(f"    📜 {name} — {len(qs)} quest(s) ({done} done)")
    return 0


def cmd_todo(args) -> int:
    """Manage a quest's personal My To-Do sidecar file.

    Actions: add | done | undone | rm | note | list | edit. The sidecar lives
    at ~/.claude/quest/data/notes/<proj>__<quest>.md — user-owned, written
    directly or via these commands, and never touched by autosync.
    """
    data = load()
    project = get_project(data, args.project_id)       # validates project
    quest = find_quest(project, args.quest_id)         # validates quest (sys.exit on miss)
    path = sidecar.sidecar_path(args.project_id, args.quest_id)
    action = args.action
    rest = args.rest

    if action == "edit":
        print(path)
        return 0

    if action == "list":
        print(f"# {path}")
        if path.exists():
            print(path.read_text(encoding="utf-8").rstrip("\n"))
        else:
            print('(no sidecar yet — add one with: quest.py todo add <proj> <quest> "...")')
        return 0

    # Interpret the trailing args per action.
    if action in ("add", "note"):
        text_arg = " ".join(rest).strip()
        if not text_arg:
            sys.exit(
                f'ERROR: "todo {action}" needs text — '
                f'quest.py todo {action} <proj> <quest> "..."'
            )
    else:  # done | undone | rm
        if not rest:
            sys.exit(
                f'ERROR: "todo {action}" needs an index N — '
                f"quest.py todo {action} <proj> <quest> <N>"
            )
        try:
            n_arg = int(rest[0])
        except ValueError:
            sys.exit(f'ERROR: "todo {action}" index must be an integer (got {rest[0]!r})')
        if n_arg < 1:
            sys.exit("ERROR: todo index must be >= 1")

    text = path.read_text(encoding="utf-8") if path.exists() else ""

    if action == "add":
        text = sidecar.ensure_header(text, quest["name"])
        text = sidecar.append_todo(text, text_arg)
    elif action == "note":
        text = sidecar.ensure_header(text, quest["name"])
        text = sidecar.append_note(text, text_arg)
    elif action in ("done", "undone"):
        try:
            text = sidecar.set_todo_done(text, n_arg, action == "done")
        except IndexError as e:
            sys.exit(f"ERROR: {e}")
    elif action == "rm":
        try:
            text = sidecar.remove_todo(text, n_arg)
        except IndexError as e:
            sys.exit(f"ERROR: {e}")

    path.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
    print(f"todo {action}: {args.project_id}/{args.quest_id} → {path}")
    return render_now()


# ---- claim/unclaim (session ↔ quest binding for statusline) ----

def _path_map() -> list[tuple[str, str]]:
    """Read project path_map from ~/.claude/quest/config.json. [] if absent."""
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        return [(e["path"], e["id"]) for e in cfg.get("path_map", [])
                if e.get("path") and e.get("id")]
    except Exception:
        return []


def auto_detect_quest(cwd: str | None = None) -> tuple[str | None, str | None]:
    """Best-effort detect (project_id, quest_id) for the current session.

    Strategy:
      1. Map cwd → project_id via path_map.
      2. Inside that project, return the most-recently-touched current quest
         (by `last_touched` ISO string; falls back to first listed if missing).
      3. If no current quest, returns (project_id, None) — caller falls back
         to project home URL.
      4. If no project resolvable, returns (None, None) — caller falls back
         to dashboard root.
    """
    import os as _os
    cwd = cwd or _os.getcwd()
    pid = None
    # Match prefix when cwd is exactly the prefix OR starts with `prefix`
    # followed by a separator (`/`, `-`, `_`). Lets one entry like
    # `~/LimorAI` cover all worktrees `LimorAI-Limor`, `LimorAI-staging`,
    # while rejecting `LimorAI2` / `LimorAIxyz`.
    for prefix, candidate in _path_map():
        prefix = prefix.rstrip("/")
        if cwd == prefix or any(cwd.startswith(prefix + sep) for sep in ("/", "-", "_")):
            pid = candidate
            break
    if pid is None:
        return (None, None)

    try:
        data = load()
    except Exception:
        return (pid, None)
    project = data.get("projects", {}).get(pid)
    if not project:
        return (pid, None)
    currents = [q for q in project.get("quests", []) if q.get("status") == "current"]
    if not currents:
        return (pid, None)
    # Most-recently-touched current — newest last_touched wins
    currents.sort(key=lambda q: q.get("last_touched", ""), reverse=True)
    return (pid, currents[0].get("id"))


def _kebab(s: str) -> str:
    """Kebab-case for session_name vs quest_id comparison."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def cmd_claim(args) -> int:
    """Bind THIS session to a quest. With no args, claims whatever
    auto-detect would pick (locks it in even when focus drifts)."""
    # GC dead-session claim files on every claim (cheapest moment to sweep —
    # we're already writing run/ + the operator is intentionally touching the
    # claim layer).
    try:
        _gc_dead_session_claims()
    except Exception:
        pass
    key = session_key()
    if not key:
        print("ERROR: could not resolve CC session identity (not running under claude?)",
              file=sys.stderr)
        return 2
    RUN.mkdir(parents=True, exist_ok=True)

    # Resolve target — explicit args win, else auto-detect.
    project_id = getattr(args, "project_id", None)
    quest_id = getattr(args, "quest_id", None)
    session_name_arg = (getattr(args, "session_name", None) or "").strip()
    session_slug = _kebab(session_name_arg) if session_name_arg else ""

    if not project_id or not quest_id:
        ap, aq = auto_detect_quest()
        project_id = project_id or ap

        # Name-based match: if --session-name is provided AND substring-matches
        # an active quest id (either direction), prefer that over most-recent.
        # Prevents the "two sessions in same cwd both auto-claim same quest" bug
        # when the operator deliberately named the session for the work it does.
        if project_id and session_slug and not quest_id:
            try:
                _data_peek = load()
                project_peek = _data_peek.get("projects", {}).get(project_id) or {}
                currents = [q for q in project_peek.get("quests", [])
                            if q.get("status") == "current"]
                matched = next(
                    (q for q in currents
                     if (session_slug in q.get("id", "")
                         or q.get("id", "") in session_slug)),
                    None,
                )
                if matched:
                    quest_id = matched["id"]
            except Exception:
                pass  # fall through to default auto-detect

        quest_id = quest_id or aq

    if not project_id:
        print("ERROR: no project resolvable from cwd; pass <project> <quest-id> explicitly",
              file=sys.stderr)
        return 2
    if not quest_id:
        print(f"ERROR: no current quest in project '{project_id}' to auto-detect; "
              f"pass <quest-id> explicitly", file=sys.stderr)
        return 2

    # Validate the quest exists
    data = load()
    project = data.get("projects", {}).get(project_id)
    if not project:
        print(f"ERROR: project '{project_id}' not found", file=sys.stderr)
        return 2
    quest = next((q for q in project.get("quests", []) if q.get("id") == quest_id), None)
    if not quest:
        print(f"ERROR: quest '{quest_id}' not found in project '{project_id}'", file=sys.stderr)
        return 2

    claim_file_for(key).write_text(f"{project_id}/{quest_id}\n", encoding="utf-8")

    # Lock sidecar: when --lock, write `.lock` next to claim. The prompt-rebind
    # hook honors this marker and skips auto-rebind. /quest unlock clears it.
    lock_path = claim_file_for(key).with_suffix(".quest.lock")
    if getattr(args, "lock", False):
        lock_path.write_text(f"{project_id}/{quest_id}\n", encoding="utf-8")
    else:
        # Clearing claim: drop any stale lock so the next claim isn't sticky.
        try: lock_path.unlink()
        except FileNotFoundError: pass

    # Sidecar .name file — captures the chosen session name next to the claim.
    # Survives independent of quests.json mutations and supports multiple live
    # sessions on the same quest (each session has its own sidecar).
    session_name = getattr(args, "session_name", None) or ""
    session_name = session_name.strip()
    name_sidecar = claim_file_for(key).with_suffix(".name")
    if session_name:
        name_sidecar.write_text(session_name + "\n", encoding="utf-8")
    else:
        # Clean stale sidecar if the new claim has no name
        try: name_sidecar.unlink()
        except FileNotFoundError: pass

    # Stamp session_name onto the quest so the dashboard title can render
    # "Quest Name (session-name)" when they differ. Last-claimer-wins.
    # session_name comes from --session-name flag (CC --name passed through).
    if session_name:
        # Only store if it adds info — empty or kebab-equals-qid is noise.
        if _kebab(session_name) != quest_id:
            quest["claimed_session_name"] = session_name
        else:
            quest.pop("claimed_session_name", None)
        save(data)
        # Re-render so the title updates immediately
        try:
            subprocess.run(["python3", str(RENDER)], capture_output=True, timeout=10)
        except Exception:
            pass

    print(f"Claimed: {project_id}/{quest_id} (#{quest.get('n','?')} {quest.get('name','?')})")
    if session_name:
        print(f"Session name: {session_name}")
    print(f"Statusline link: {DASHBOARD_URL}/{project_id}/plan-card.html?q={quest_id}")
    return 0


def cmd_unclaim(args) -> int:
    """Remove the claim file for THIS session. Statusline reverts to auto-detect.
    Also clears claimed_session_name from the previously-claimed quest so the
    dashboard title drops the session suffix."""
    key = session_key()
    if not key:
        print("ERROR: could not resolve CC session identity", file=sys.stderr)
        return 2
    cf = claim_file_for(key)
    if not cf.exists():
        print("No active claim for this session.")
        return 0

    # Read what was claimed → clear claimed_session_name on that quest
    try:
        target = cf.read_text(encoding="utf-8").strip()
        project_id, quest_id = target.split("/", 1)
        data = load()
        project = data.get("projects", {}).get(project_id)
        if project:
            quest = next((q for q in project.get("quests", []) if q.get("id") == quest_id), None)
            if quest and "claimed_session_name" in quest:
                del quest["claimed_session_name"]
                save(data)
                # Re-render so title clears
                try:
                    subprocess.run(["python3", str(RENDER)], capture_output=True, timeout=10)
                except Exception:
                    pass
    except Exception:
        pass

    cf.unlink()
    # Clean sidecar name file if present
    try: cf.with_suffix(".name").unlink()
    except FileNotFoundError: pass
    print(f"Unclaimed (was: {cf.name})")
    return 0


def cmd_claimed(args) -> int:
    """Print the current claim (project/quest-id) for THIS session, or auto-detected fallback."""
    key = session_key()
    if not key:
        print("ERROR: could not resolve CC session identity", file=sys.stderr)
        return 2
    cf = claim_file_for(key)
    if cf.exists():
        target = cf.read_text(encoding="utf-8").strip()
        print(f"claim: {target}  (explicit, file: {cf.name})")
    else:
        ap, aq = auto_detect_quest()
        if ap and aq:
            print(f"claim: {ap}/{aq}  (auto-detect)")
        elif ap:
            print(f"claim: {ap}/-  (project home — no current quest)")
        else:
            print("claim: -  (no project resolvable from cwd)")
    return 0


def cmd_unlock(args) -> int:
    """Remove the lock sidecar for THIS session. Re-enables auto-rebind.

    Does NOT touch the claim file itself — use /quest unclaim to clear that.
    """
    key = session_key()
    if not key:
        print("ERROR: could not resolve CC session identity", file=sys.stderr)
        return 2
    lock_path = claim_file_for(key).with_suffix(".quest.lock")
    if not lock_path.exists():
        print("No lock active for this session.")
        return 0
    lock_path.unlink()
    print(f"Unlocked: {lock_path.name} removed. Auto-rebind re-enabled.")
    return 0


def cmd_rebind_stats(args) -> int:
    """Summarize recent prompt-rebind hook activity from rebind.jsonl.

    Reads ~/.claude/quest/log/rebind.jsonl, filters to the last N days
    (default 7), reports action distribution, threshold-boundary candidates
    (near rebind threshold — likely tune targets), and any recent rebinds
    on THIS session.
    """
    log_path = ROOT / "quest" / "log" / "rebind.jsonl"
    if not log_path.is_file():
        print("No rebind log yet. Hook has not fired or is disabled.")
        return 0
    import time as _t
    cutoff = _t.time() - (args.days * 86400)
    entries: list[dict] = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                ts = e.get("ts", "")
                try:
                    et = _t.mktime(_t.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
                except Exception:
                    continue
                if et >= cutoff:
                    entries.append(e)
    except Exception as exc:
        print(f"ERROR reading log: {exc}", file=sys.stderr)
        return 2
    if not entries:
        print(f"No hook activity in last {args.days} day(s).")
        return 0

    print(f"=== /quest rebind-stats — last {args.days} day(s) ({len(entries)} fires) ===\n")

    actions: dict[str, int] = {}
    acteds: dict[str, int] = {}
    for e in entries:
        actions[e.get("action", "?")] = actions.get(e.get("action", "?"), 0) + 1
        acteds[e.get("acted", "?")] = acteds.get(e.get("acted", "?"), 0) + 1
    print("Action distribution (what the scorer decided):")
    for a, n in sorted(actions.items(), key=lambda kv: -kv[1]):
        print(f"  {a:<24} {n}")
    print("\nActed distribution (what the hook actually did):")
    for a, n in sorted(acteds.items(), key=lambda kv: -kv[1]):
        print(f"  {a:<24} {n}")

    # Threshold-tune candidates: rebinds with thin margin OR suggests near rebind threshold
    print("\nTune candidates (rebinds with margin <4, OR suggests with score >=4.5):")
    cands = [
        e for e in entries
        if (e.get("action") == "rebind" and 0 < e.get("margin", 0) < 4)
        or (e.get("action") == "suggest" and e.get("score", 0) >= 4.5)
    ]
    if not cands:
        print("  (none — thresholds appear well-calibrated)")
    else:
        for e in cands[-15:]:  # most recent 15
            print(f"  {e['ts']} {e.get('action','?'):<8} top={e.get('top','-')[:35]:<37} "
                  f"s={e.get('score',0):<5} m={e.get('margin',0):<5} '{e.get('prompt','')[:50]}'")

    # This session's rebinds
    cur_sk = session_key()
    if cur_sk:
        my = [e for e in entries if e.get("sk") == cur_sk and e.get("acted") in ("rebound", "rebound-dryrun")]
        if my:
            print(f"\nThis session (sk={cur_sk}) — {len(my)} actual rebind(s):")
            for e in my[-10:]:
                print(f"  {e['ts']} → {e.get('top','-')[:50]}  (from: {e.get('from','none')})")

    return 0


_TAG_RE = re.compile(r"^[A-Za-z0-9_:./\-]{1,64}$")


def _normalize_tag(raw: str) -> str:
    """Same validation as server._normalize_tag — kept here for CLI use without
    importing server (which would start the HTTP module-level state)."""
    t = (raw or "").strip()
    return t if t and _TAG_RE.match(t) else ""


def _dedup_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def cmd_tag(args) -> int:
    """quest tag <project> <quest> add|remove|list <values...>

    `add` / `remove` accept multiple comma-separated tokens. `list` ignores
    extra args."""
    action = args.action
    data = load()
    project = get_project(data, args.project_id)
    quest = find_quest(project, args.quest_id)

    if action == "list":
        tags = quest.get("tags") or []
        if not tags:
            print("(no tags)")
        else:
            for t in tags:
                print(t)
        return 0

    raw = ",".join(args.values or [])
    candidates = [_normalize_tag(t) for t in raw.split(",")]
    clean = [t for t in candidates if t]
    if not clean:
        print(f"ERROR: no valid tag values (allowed chars: A-Z a-z 0-9 _ : . / -, max 64)",
              file=sys.stderr)
        return 2

    existing = list(quest.get("tags") or [])
    if action == "add":
        existing.extend(clean)
        existing = _dedup_preserve_order(existing)
    elif action == "remove":
        existing = [t for t in existing if t not in clean]
    else:
        print(f"ERROR: unknown action '{action}'", file=sys.stderr)
        return 2

    if existing:
        quest["tags"] = existing
    elif "tags" in quest:
        del quest["tags"]
    save(data)
    print(f"{action}: {', '.join(clean)}")
    print(f"tags now: {', '.join(quest.get('tags') or []) or '(none)'}")
    return render_now()


def _bind_label_for_current_session(name_arg: str) -> tuple[str, str] | None:
    """Resolve the friendly session label for `bind`.

    Priority: explicit --session-name > current session's .name sidecar >
    session_key (the raw pid-ticks identifier — readable but ugly).

    Returns (tag, label) or None when nothing usable is available."""
    label = (name_arg or "").strip()
    if not label:
        key = session_key()
        if key:
            sidecar = claim_file_for(key).with_suffix(".name")
            if sidecar.exists():
                try:
                    label = sidecar.read_text(encoding="utf-8").strip()
                except OSError:
                    label = ""
            if not label:
                label = key
    if not label:
        return None
    tag = _normalize_tag(f"session:{label}")
    if not tag:
        return None
    return tag, label


def cmd_bind(args) -> int:
    """quest bind <project> <quest> [--session-name X]

    Adds a `session:<name>` tag so this chat session is linked to the quest."""
    resolved = _bind_label_for_current_session(getattr(args, "session_name", "") or "")
    if not resolved:
        print("ERROR: no session identity available — pass --session-name explicitly "
              "or run inside a `claude` session.",
              file=sys.stderr)
        return 2
    tag, label = resolved
    data = load()
    project = get_project(data, args.project_id)
    quest = find_quest(project, args.quest_id)
    existing = list(quest.get("tags") or [])
    if tag in existing:
        print(f"already bound: {tag}")
        return 0
    existing.append(tag)
    quest["tags"] = existing
    save(data)
    print(f"bound: {project['name']} / {quest['name']} <- {tag}")
    print(f"      (session label: {label})")
    return render_now()


def cmd_unbind(args) -> int:
    """quest unbind [<project> <quest>]

    With no args: remove the current session's tag from EVERY quest carrying it.
    With both args: remove only from that one quest."""
    resolved = _bind_label_for_current_session(getattr(args, "session_name", "") or "")
    if not resolved:
        print("ERROR: no session identity available — nothing to unbind.",
              file=sys.stderr)
        return 2
    tag, label = resolved
    data = load()
    touched: list[tuple[str, str]] = []
    if args.project_id and args.quest_id:
        project = get_project(data, args.project_id)
        quest = find_quest(project, args.quest_id)
        tags = quest.get("tags") or []
        if tag in tags:
            quest["tags"] = [t for t in tags if t != tag]
            if not quest["tags"]:
                del quest["tags"]
            touched.append((args.project_id, args.quest_id))
    else:
        for pid, project in data.get("projects", {}).items():
            for q in project.get("quests", []) or []:
                tags = q.get("tags") or []
                if tag in tags:
                    q["tags"] = [t for t in tags if t != tag]
                    if not q["tags"]:
                        del q["tags"]
                    touched.append((pid, q.get("id", "?")))
    if not touched:
        print(f"no quests carry tag '{tag}' — nothing to do.")
        return 0
    save(data)
    print(f"unbound {tag} from {len(touched)} quest(s):")
    for pid, qid in touched:
        print(f"  - {pid}/{qid}")
    return render_now()


def cmd_mine(args) -> int:
    """quest mine — list every quest tagged with this session's name."""
    resolved = _bind_label_for_current_session(getattr(args, "session_name", "") or "")
    if not resolved:
        print("ERROR: no session identity — bind a quest first or pass --session-name.",
              file=sys.stderr)
        return 2
    tag, label = resolved
    data = load()
    hits: list[tuple[str, dict]] = []
    for pid, project in data.get("projects", {}).items():
        for q in project.get("quests", []) or []:
            if tag in (q.get("tags") or []):
                hits.append((pid, q))
    if not hits:
        print(f"no quests bound to '{label}'.")
        print(f"   Bind one with: quest bind <project> <quest-id> --session-name {label}")
        return 0
    print(f"Quests bound to '{label}':")
    for pid, q in hits:
        status = q.get("status", "?")
        pct = int(100 * (q.get("progress") or 0))
        print(f"  - {pid:8s} #{q.get('n','?'):>2} {q.get('name','?'):40s} "
              f"[{status:7s} {pct:>3}%]")
    return 0


# ---- argparse setup ----

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quest", description="Manage RPG-style project roadmaps.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="Print state of all projects + dashboard URL")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("init", help="Create a new project")
    s.add_argument("project_id")
    s.add_argument("--name")
    s.add_argument("--subtitle", default="")
    s.add_argument("--theme", default="pokemon")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("add", help="Add a quest to a project")
    s.add_argument("project_id")
    s.add_argument("name")
    s.add_argument("--id", help="quest id slug (default: derived from name)")
    s.add_argument("--desc", default="")
    s.add_argument("--landmark", choices=LANDMARKS)
    s.add_argument("--xp", type=int)
    s.add_argument("--plan", default="")
    s.add_argument("--next", default="")
    s.add_argument("--locked", action="store_true", help="add as locked even if no current exists")
    s.add_argument("--no-claim", dest="no_claim", action="store_true",
                   help="don't auto-claim this session for the new quest (default: auto-claim)")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("update", help="Update a quest's fields")
    s.add_argument("project_id")
    s.add_argument("quest_id")
    s.add_argument("--progress", type=float)
    s.add_argument("--next")
    s.add_argument("--name")
    s.add_argument("--desc")
    s.add_argument(
        "--problem",
        help="Plain-language Problem statement shown on the plan card. Keep it human-friendly — no jargon, no commit SHAs, no internal acronyms. Pass empty string to clear.",
    )
    s.add_argument(
        "--solution",
        help="Plain-language Solution statement shown on the plan card. Same rules as --problem.",
    )
    s.add_argument("--landmark", choices=LANDMARKS)
    s.add_argument("--status", choices=["done", "current", "locked"])
    s.add_argument(
        "--add-link",
        dest="add_link",
        action="append",
        default=None,
        metavar="URL|LABEL|DESC",
        help='Append a link entry. Format: "URL|LABEL|DESC" (LABEL and DESC optional). Repeatable.',
    )
    s.add_argument(
        "--clear-links",
        dest="clear_links",
        action="store_true",
        help="Remove all link entries from this quest.",
    )
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("done", help="Mark a quest done; awards XP, may promote next")
    s.add_argument("project_id")
    s.add_argument("quest_id")
    s.set_defaults(func=cmd_done)

    s = sub.add_parser("theme", help="Switch theme for a project")
    s.add_argument("project_id")
    s.add_argument("theme_name")
    s.set_defaults(func=cmd_theme)

    s = sub.add_parser("style", help="Set the home-index card accent + icon for a project")
    s.add_argument("project_id")
    s.add_argument("--accent", help="6-digit hex color, e.g. #ff6a3a (empty string = clear)")
    s.add_argument("--icon", help=f"Landmark icon name. One of: {', '.join(LANDMARKS)} (empty string = clear)")
    s.set_defaults(func=cmd_style)

    s = sub.add_parser("render", help="Regenerate all HTML")
    s.set_defaults(func=cmd_render)

    s = sub.add_parser("reset", help="Close current chapter — archive done/active quests, start fresh map")
    s.add_argument("project_id")
    s.add_argument("--chapter", required=True, help="Name for the archived chapter (e.g. 'q2-2026-bundle-a')")
    s.add_argument("--clean", action="store_true", help="Also archive locked quests (default: locked survive into the new chapter)")
    s.add_argument("--yes", "-y", action="store_true", help="Skip preview and commit. Without this, --yes prints a preview and exits.")
    s.set_defaults(func=cmd_reset)

    s = sub.add_parser("chapters", help="List archived chapters")
    s.add_argument("project_id", nargs="?", help="Optional — defaults to all projects")
    s.set_defaults(func=cmd_chapters)

    s = sub.add_parser(
        "todo",
        help="Manage a quest's personal My To-Do sidecar (add/done/undone/rm/note/list/edit)",
    )
    s.add_argument("action", choices=["add", "done", "undone", "rm", "note", "list", "edit"])
    s.add_argument("project_id")
    s.add_argument("quest_id")
    s.add_argument(
        "rest",
        nargs="*",
        help='text for add|note, or index N for done|undone|rm (nothing for list|edit)',
    )
    s.set_defaults(func=cmd_todo)

    s = sub.add_parser("tag", help="Manage a quest's freeform tags (add/remove/list)")
    s.add_argument("project_id")
    s.add_argument("quest_id")
    s.add_argument("action", choices=["add", "remove", "list"])
    s.add_argument("values", nargs="*",
                   help="Tag(s) to add/remove. Comma- or space-separated. "
                        "Allowed: A-Z a-z 0-9 _ : . / - (max 64 chars).")
    s.set_defaults(func=cmd_tag)

    s = sub.add_parser("bind",
                       help="Tag a quest with session:<name> to link THIS chat session to it")
    s.add_argument("project_id")
    s.add_argument("quest_id")
    s.add_argument("--session-name", default="",
                   help="Session label to use. Defaults to current session's "
                        ".name sidecar, then to the raw session_key.")
    s.set_defaults(func=cmd_bind)

    s = sub.add_parser("unbind",
                       help="Remove THIS session's tag — optionally from a specific quest")
    s.add_argument("project_id", nargs="?", help="Optional — defaults to ALL quests carrying the tag")
    s.add_argument("quest_id", nargs="?")
    s.add_argument("--session-name", default="",
                   help="Override the session label to unbind.")
    s.set_defaults(func=cmd_unbind)

    s = sub.add_parser("mine",
                       help="List every quest tagged with this session's session:<name>")
    s.add_argument("--session-name", default="",
                   help="Override the session label to look up.")
    s.set_defaults(func=cmd_mine)

    s = sub.add_parser("claim", help="Bind THIS session to a quest (statusline link)")
    s.add_argument("project_id", nargs="?", help="Project id (auto-detected from cwd if omitted)")
    s.add_argument("quest_id", nargs="?", help="Quest id (auto-detected if omitted)")
    s.add_argument("--session-name", default="",
                   help="Session label to stamp on the quest (e.g. CC --name). Shown on dashboard title when it differs from quest id.")
    s.add_argument("--lock", action="store_true",
                   help="Prevent prompt-rebind hook from auto-switching this claim. Use /quest unlock to re-enable.")
    s.set_defaults(func=cmd_claim)

    s = sub.add_parser("unclaim", help="Remove THIS session's claim — revert to auto-detect")
    s.set_defaults(func=cmd_unclaim)

    s = sub.add_parser("claimed", help="Print the current claim for THIS session")
    s.set_defaults(func=cmd_claimed)

    s = sub.add_parser("unlock", help="Remove the lock sidecar — re-enable prompt-rebind auto-switch")
    s.set_defaults(func=cmd_unlock)

    s = sub.add_parser("rebind-stats",
                       help="Summarize recent prompt-rebind hook activity (tune candidates, this session's rebinds)")
    s.add_argument("--days", type=int, default=7, help="Window in days (default 7)")
    s.set_defaults(func=cmd_rebind_stats)

    return p


def main() -> int:
    p = build_parser()
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
