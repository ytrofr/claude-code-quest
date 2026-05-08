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
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path.home() / ".claude"
DATA = ROOT / "quest" / "data" / "quests.json"
THEMES = ROOT / "skills" / "quest" / "themes"
RENDER = ROOT / "skills" / "quest" / "render.py"
DASHBOARD_URL = "http://localhost:8770"

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
    has_current = any(q.get("status") == "current" for q in project["quests"])
    status = "locked" if (args.locked or has_current) else "current"
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
    if args.landmark is not None:
        if args.landmark not in LANDMARKS:
            sys.exit(f"ERROR: landmark must be one of {LANDMARKS}")
        quest["landmark"] = args.landmark
        changes.append(f"landmark={args.landmark}")
    if args.status is not None:
        if args.status not in ("done", "current", "locked"):
            sys.exit("ERROR: status must be done|current|locked")
        # If setting current, demote any other current to locked
        if args.status == "current":
            for q in project["quests"]:
                if q is not quest and q.get("status") == "current":
                    q["status"] = "locked"
        quest["status"] = args.status
        changes.append(f"status={args.status}")
    save(data)
    print(f"Updated {args.project_id}/{args.quest_id}: {', '.join(changes) if changes else '(no changes)'}")
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
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("update", help="Update a quest's fields")
    s.add_argument("project_id")
    s.add_argument("quest_id")
    s.add_argument("--progress", type=float)
    s.add_argument("--next")
    s.add_argument("--name")
    s.add_argument("--desc")
    s.add_argument("--landmark", choices=LANDMARKS)
    s.add_argument("--status", choices=["done", "current", "locked"])
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

    return p


def main() -> int:
    p = build_parser()
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
