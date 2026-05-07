#!/usr/bin/env python3
"""quest autosync — background script triggered by plan-write hook.

Add-or-update behaviour:
  - New plan file: append a new quest (status=current if no other current).
  - Existing plan: scan content for §13 checkboxes → progress + tasks list,
    update last_touched, pick up branch + last commit from local git.

Pure local Python, zero LLM calls, ~30ms typical. ALL errors swallowed
and logged; never raises.

Usage: autosync.py <plan_file_path>
"""

import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path.home() / ".claude"
DATA = ROOT / "quest" / "data" / "quests.json"
LOCK = ROOT / "quest" / "run" / "autosync.lock"
LOG = ROOT / "quest" / "logs" / "autosync.log"
RENDER = ROOT / "skills" / "quest" / "render.py"
CONFIG = ROOT / "quest" / "config.json"


def load_project_path_map() -> list:
    """Read PROJECT_PATH_MAP from ~/.claude/quest/config.json. User-owned.

    Schema: {"path_map": [{"path": "/home/.../proj", "id": "proj"}, ...]}
    Order matters in the file: more-specific prefixes first.
    Returns [] if config missing or unparseable (autosync still works,
    just falls through to BLUF-line resolution)."""
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        return [(e["path"], e["id"]) for e in cfg.get("path_map", []) if e.get("path") and e.get("id")]
    except Exception:
        return []


# Lazy module-level load — file may not exist on a fresh install.
PROJECT_PATH_MAP = load_project_path_map()

LANDMARKS = ["house", "tower", "mill", "bridge", "camp", "cave", "castle"]


def log_msg(msg: str) -> None:
    """Append timestamped line to autosync log."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass  # logging failures must never crash autosync


# Backward-compat alias: existing call sites used `log()`.
log = log_msg


def slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "quest"


def detect_project(plan_path: Path) -> str | None:
    """3-tier resolution: BLUF Project: line → cwd-vs-registry → None."""
    # Tier 1: BLUF "Project:" or "Branch:" line — tolerates markdown prefixes:
    #   leading whitespace, `>` blockquote, `-`/`*` bullet, single or combined.
    # Examples that match: "**Project**: ogas", "> **Project**: ogas",
    #   "  - Project: ogas", "Project: ogas"
    try:
        text = plan_path.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^[\s>*\-]*\*\*Project\*\*\s*:\s*(\S+)", text, re.MULTILINE | re.IGNORECASE)
        if not m:
            m = re.search(r"^[\s>*\-]*Project\s*:\s*(\S+)", text, re.MULTILINE | re.IGNORECASE)
        if m:
            cand = m.group(1).strip("`\"' ").lower()
            return cand
    except Exception as e:
        log(f"WARN read plan for BLUF: {e}")

    # Tier 2: plan file path against registry
    plan_str = str(plan_path)
    for prefix, pid in PROJECT_PATH_MAP:
        if plan_str.startswith(prefix):
            return pid

    # Tier 3: cwd against registry (for ~/.claude/plans/* files written from a project dir)
    try:
        cwd = os.getcwd()
        for prefix, pid in PROJECT_PATH_MAP:
            if cwd.startswith(prefix):
                return pid
    except Exception:
        pass

    return None


_BOX_LINE = re.compile(r"^([ \t>*-]*)\[([ xX])\]\s+(.+?)$", re.MULTILINE)
_SUBBULLET = re.compile(r"^[ \t]+[-*+]\s+(.+?)$")


def parse_plan_progress(plan_text: str) -> dict:
    """Extract tasks + progress from plan markdown.

    Each task may have problem/solution from sub-bullets directly under it:
      - [x] Task title
        - Problem: short problem statement
        - Solution: short fix approach

    Strategy:
      1. If Section 13 exists, parse only its checkboxes (canonical signal).
      2. Otherwise fall back to all checkboxes in the plan body.
      3. For each box, scan SUBSEQUENT lines:
         - sub-bullet starting "Problem:" → task.problem
         - sub-bullet starting "Solution:" → task.solution
         - other sub-bullet → task.brief (first one only)
         - non-sub-bullet line → end of this task's brief block

    Returns: {tasks: [{title, done, problem?, solution?, brief?}],
              progress: float|None, source: str}
    """
    if not plan_text:
        return {"tasks": [], "progress": None, "source": "empty"}

    sec13 = re.search(
        r"^##\s+Section\s+13\b.*?(?=^##\s+(?:Section|\d)|\Z)",
        plan_text, re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    target = sec13.group(0) if sec13 else plan_text
    source = "section_13" if sec13 else "fallback_all"

    # Walk the lines, collecting boxes + their sub-bullets. We split on \n so
    # we can look ahead per task (regex match-only loses the structure).
    lines = target.split("\n")
    tasks: list[dict] = []
    current: dict | None = None

    def _flush() -> None:
        nonlocal current
        if current is not None:
            tasks.append(current)
            current = None

    for line in lines:
        m = _BOX_LINE.match(line)
        if m:
            _flush()
            mark = m.group(2).lower()
            title = m.group(3).strip()
            title = re.sub(r"\s+`[^`]*`\s*$", "", title)
            current = {"title": title[:120], "done": mark == "x"}
            continue

        if current is None:
            continue

        sub = _SUBBULLET.match(line)
        if sub:
            text = sub.group(1).strip()[:200]
            low = text.lower()
            if low.startswith("problem:") or low.startswith("problem —") or low.startswith("problem -"):
                current["problem"] = text.split(":", 1)[1].strip() if ":" in text else text[8:].strip()
            elif low.startswith("solution:") or low.startswith("solution —") or low.startswith("solution -"):
                current["solution"] = text.split(":", 1)[1].strip() if ":" in text else text[9:].strip()
            elif "brief" not in current:
                current["brief"] = text
            continue

        # Blank line keeps us "inside" the task; non-blank non-sub-bullet ends it
        if line.strip() == "":
            continue
        _flush()

    _flush()

    if not tasks:
        return {"tasks": [], "progress": None, "source": source + "_no_boxes"}

    done = sum(1 for t in tasks if t["done"])
    progress = round(done / len(tasks), 3)
    return {"tasks": tasks, "progress": progress, "source": source}


def get_git_meta(plan_path: Path) -> dict:
    """Walk up from plan file looking for a git repo. Return current branch +
    last commit. {} on any failure (not a git repo, missing git, timeout)."""
    try:
        d = plan_path.parent
        repo = None
        for _ in range(8):
            if (d / ".git").exists():
                repo = d
                break
            if d == d.parent:
                break
            d = d.parent
        if repo is None:
            return {}

        branch_proc = subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True, text=True, timeout=2,
        )
        log_proc = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%h|%s|%cI"],
            capture_output=True, text=True, timeout=2,
        )
        branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else ""
        log = log_proc.stdout.strip() if log_proc.returncode == 0 else ""

        out = {}
        if branch:
            out["branch"] = branch
        if log and "|" in log:
            parts = log.split("|", 2)
            if len(parts) == 3:
                sha, msg, date = parts
                out["last_commit"] = {
                    "sha": sha,
                    "msg": msg.strip()[:120],
                    "date": date,
                }
        return out
    except Exception as e:
        log_msg(f"WARN git meta: {e}")
        return {}


def derive_quest(plan_path: Path, n: int) -> dict:
    """Build a quest dict from a plan file."""
    name = plan_path.stem
    # Strip leading "1-" / "2026-05-07-" style prefixes for display
    display_name = re.sub(r"^\d+[-_]", "", name).replace("-", " ").replace("_", " ").title()

    # Try to extract description from first H1 or BLUF Solution line
    desc = ""
    try:
        text = plan_path.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"\*\*Solution\*\*\s*:\s*(.+)", text)
        if m:
            desc = m.group(1).strip()[:200]
        else:
            m = re.search(r"^#\s+(.+)", text, re.MULTILINE)
            if m:
                desc = m.group(1).strip()[:200]
    except Exception:
        pass

    return {
        "id": slug(name),
        "n": n,
        "name": display_name,
        "desc": desc,
        "landmark": LANDMARKS[(n - 1) % len(LANDMARKS)],
        "status": "locked",  # caller decides current vs locked
        "progress": 0.0,
        "xp_reward": 25,
        "plan": plan_path.name,
        "next_step": "",
    }


def render_now() -> None:
    try:
        subprocess.run(["python3", str(RENDER)], capture_output=True, text=True, timeout=10)
    except Exception as e:
        log(f"WARN render: {e}")


def update_existing_quest(quest: dict, plan_path: Path) -> dict:
    """Refresh tasks, progress, last_touched, branch, last_commit from plan
    content + git. Returns dict of {field: change} for logging. Mutates quest.

    Conservative: never overwrites with empty/None. Manual /quest update wins
    if user has set values that the parser can't infer."""
    changes = {}
    try:
        text = plan_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        log_msg(f"WARN read plan for parse: {e}")
        return changes

    parsed = parse_plan_progress(text)
    if parsed["tasks"]:
        old_tasks = quest.get("tasks", [])
        if parsed["tasks"] != old_tasks:
            quest["tasks"] = parsed["tasks"]
            changes["tasks"] = f"{len(parsed['tasks'])} ({parsed['source']})"
    if parsed["progress"] is not None:
        old_progress = quest.get("progress", 0)
        if abs(parsed["progress"] - old_progress) > 0.001:
            quest["progress"] = parsed["progress"]
            changes["progress"] = f"{old_progress:.2f}→{parsed['progress']:.2f}"

    git_meta = get_git_meta(plan_path)
    for k, v in git_meta.items():
        if v and quest.get(k) != v:
            quest[k] = v
            changes[k] = "updated"

    # Always bump last_touched on any update event
    new_ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    quest["last_touched"] = new_ts
    if changes:
        changes["last_touched"] = new_ts

    return changes


def autosync(plan_path: Path) -> None:
    """Main: detect project, append-or-update quest, re-render. Never raises."""
    if not plan_path.exists():
        log_msg(f"SKIP missing plan: {plan_path}")
        return

    project_id = detect_project(plan_path)
    if not project_id:
        log_msg(f"SKIP no project resolvable for {plan_path}")
        return

    if not DATA.exists():
        log_msg(f"SKIP quests.json missing: {DATA}")
        return

    try:
        data = json.loads(DATA.read_text(encoding="utf-8"))
    except Exception as e:
        log_msg(f"ERROR parse quests.json: {e}")
        return

    if project_id not in data.get("projects", {}):
        log_msg(f"SKIP project '{project_id}' not in quests.json (resolved from {plan_path})")
        return

    project = data["projects"][project_id]
    qid = slug(plan_path.stem)

    # Find existing by id (preferred) or by plan filename match (fallback for
    # bootstrap quests whose id was set independently of filename slug).
    existing = next((q for q in project.get("quests", []) if q.get("id") == qid), None)
    if existing is None:
        existing = next(
            (q for q in project.get("quests", []) if q.get("plan") == plan_path.name),
            None,
        )

    if existing is not None:
        # UPDATE path — refresh from plan content
        changes = update_existing_quest(existing, plan_path)
        if not changes:
            log_msg(f"NOOP {project_id}/{existing['id']} no changes ({plan_path.name})")
            return
        try:
            DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as e:
            log_msg(f"ERROR write quests.json: {e}")
            return
        log_msg(f"UPDATED {project_id}/{existing['id']} {changes} ({plan_path.name})")
        render_now()
        return

    # ADD path — new plan, append quest
    n = len(project.get("quests", [])) + 1
    quest = derive_quest(plan_path, n)
    has_current = any(q.get("status") == "current" for q in project["quests"])
    quest["status"] = "locked" if has_current else "current"

    # Initial parse of plan content + git meta
    update_existing_quest(quest, plan_path)

    project["quests"].append(quest)

    try:
        DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as e:
        log_msg(f"ERROR write quests.json: {e}")
        return

    log_msg(f"ADDED {project_id}/{quest['id']} (#{n}, {quest['landmark']}, {quest['status']}) from {plan_path}")
    render_now()


def main() -> int:
    if len(sys.argv) < 2:
        log("ERROR no plan path argument")
        return 0

    plan_path = Path(sys.argv[1]).expanduser().resolve()

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        with LOCK.open("w") as lock_f:
            try:
                fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                log(f"SKIP locked (concurrent autosync) for {plan_path}")
                return 0
            try:
                autosync(plan_path)
            except Exception as e:
                log(f"ERROR autosync: {e}")
    except Exception as e:
        log(f"ERROR lock: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
