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
# BLUF Problem/Solution lines — tolerate `> `, `- `, `* ` markdown prefixes.
_BLUF_PROBLEM = re.compile(r"^[\s>*\-]*\*\*Problem\*\*\s*:\s*(.+?)$", re.MULTILINE | re.IGNORECASE)
_BLUF_SOLUTION = re.compile(r"^[\s>*\-]*\*\*Solution\*\*\s*:\s*(.+?)$", re.MULTILINE | re.IGNORECASE)
# `depends_on:` directive (anywhere in plan): `> **Depends on**: quest-id-1, quest-id-2`
_BLUF_DEPENDS = re.compile(r"^[\s>*\-]*\*\*Depends[- ]on\*\*\s*:\s*(.+?)$", re.MULTILINE | re.IGNORECASE)
# `Why:` line (motivation in 1 sentence)
_BLUF_WHY = re.compile(r"^[\s>*\-]*\*\*Why\*\*\s*:\s*(.+?)$", re.MULTILINE | re.IGNORECASE)


def _trim_sentence(text: str, cap: int = 140) -> str:
    """Cap text to first sentence OR `cap` chars, whichever is shorter.

    Preserves natural break (. ! ?) when the sentence ends within cap+20 chars.
    Never returns >cap chars; trailing ellipsis added when truncating mid-word."""
    if not text:
        return ""
    text = text.strip().rstrip(" .,;:")
    # Try to break on first sentence end within cap+20 (small overflow OK)
    m = re.search(r"^(.{15,%d}?[.!?])\s" % (cap + 20), text)
    if m:
        return m.group(1).strip()
    if len(text) <= cap:
        return text
    # Hard truncate at last word boundary before cap-3 (room for ellipsis)
    cut = text[: cap - 1]
    cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return cut + "…"


def extract_bluf(text: str) -> dict:
    """Pull Problem/Solution/Why/Depends-on from BLUF block. All optional.

    Returns {problem?, solution?, why?, depends_on?}. Caps each at 200 chars
    (leaner display); empty strings stripped."""
    out: dict = {}
    if not text:
        return out
    pm = _BLUF_PROBLEM.search(text)
    if pm:
        v = pm.group(1).strip()[:200]
        if v:
            out["problem"] = v
    sm = _BLUF_SOLUTION.search(text)
    if sm:
        v = sm.group(1).strip()[:200]
        if v:
            out["solution"] = v
    wm = _BLUF_WHY.search(text)
    if wm:
        v = wm.group(1).strip()[:200]
        if v:
            out["why"] = v
    dm = _BLUF_DEPENDS.search(text)
    if dm:
        deps = [d.strip().strip("`\"' ").lower() for d in dm.group(1).split(",")]
        deps = [d for d in deps if d and re.match(r"^[\w\-]+$", d)]
        if deps:
            out["depends_on"] = deps
    return out


def derive_lean_desc(text: str) -> str:
    """Return one-liner desc (≤140 chars). Prefers BLUF Solution, falls back to H1."""
    bluf = extract_bluf(text)
    sol = bluf.get("solution") or ""
    if sol:
        return _trim_sentence(sol, 140)
    # H1 fallback (first `# ...` line)
    m = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    if m:
        return _trim_sentence(m.group(1), 140)
    return ""


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
    """Build a quest dict from a plan file. Lean desc (≤140 char) +
    problem/solution/why/depends_on lifted from BLUF when present."""
    name = plan_path.stem
    # Strip leading "1-" / "2026-05-07-" style prefixes for display
    display_name = re.sub(r"^\d+[-_]", "", name).replace("-", " ").replace("_", " ").title()

    quest = {
        "id": slug(name),
        "n": n,
        "name": display_name,
        "desc": "",
        "landmark": LANDMARKS[(n - 1) % len(LANDMARKS)],
        "status": "locked",  # caller decides current vs locked
        "progress": 0.0,
        "xp_reward": 25,
        "plan": plan_path.name,
        "next_step": "",
    }

    try:
        text = plan_path.read_text(encoding="utf-8", errors="ignore")
        quest["desc"] = derive_lean_desc(text)
        bluf = extract_bluf(text)
        for k in ("problem", "solution", "why", "depends_on"):
            if k in bluf:
                quest[k] = bluf[k]
    except Exception as e:
        log_msg(f"WARN derive_quest: {e}")

    return quest


def render_now() -> None:
    try:
        subprocess.run(["python3", str(RENDER)], capture_output=True, text=True, timeout=10)
    except Exception as e:
        log(f"WARN render: {e}")


def update_existing_quest(quest: dict, plan_path: Path) -> dict:
    """Refresh tasks, progress, last_touched, branch, last_commit, BLUF fields
    from plan content + git. Returns dict of {field: change} for logging.
    Mutates quest.

    Conservative: never overwrites with empty/None. Manual /quest update wins
    if user has set values that the parser can't infer.

    Desc self-heals only when stored value is empty OR longer than 140 chars
    (prevents clobbering hand-set lean descriptions)."""
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

    # BLUF refresh: problem, solution, why, depends_on always update from plan.
    bluf = extract_bluf(text)
    for k in ("problem", "solution", "why", "depends_on"):
        if k in bluf and quest.get(k) != bluf[k]:
            quest[k] = bluf[k]
            changes[k] = "refreshed"

    # Desc self-heal: replace empty OR fat (>140) desc with lean version.
    desc_now = quest.get("desc") or ""
    if not desc_now or len(desc_now) > 140:
        lean = derive_lean_desc(text)
        if lean and lean != desc_now:
            quest["desc"] = lean
            changes["desc"] = f"{len(desc_now)}→{len(lean)} chars"

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


def detect_depends_hint(plan_text: str, plan_path: Path, project: dict, new_quest_id: str) -> list[str]:
    """Heuristic: scan project's existing current/locked quests for ones the new
    plan likely depends on. Return list of likely-parent quest ids.

    Triggers:
      - Plan body mentions an existing quest id verbatim (e.g. 'after `setup-quest`')
      - Plan body mentions an existing quest name (case-insensitive substring)
    Skips:
      - Self-reference (the new quest's own id/name)
      - Quests already cited in BLUF Depends-on (no false-positive nag)
    Returns empty list if no hints found."""
    bluf = extract_bluf(plan_text)
    already = set(bluf.get("depends_on") or [])

    # Strip BLUF block to avoid matching the plan's own front-matter
    body = plan_text
    bluf_match = re.search(r"^##\s+BLUF\b.*?(?=^##\s)", plan_text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if bluf_match:
        body = plan_text[:bluf_match.start()] + plan_text[bluf_match.end():]
    body_lower = body.lower()

    hints: list[str] = []
    for q in project.get("quests", []):
        qid = q.get("id", "")
        qname = q.get("name", "")
        if not qid or qid == new_quest_id or qid in already:
            continue
        # Match on:
        #  - backticked id (most precise): `qid`
        #  - bare id with word boundaries (kebab-case is rare in prose)
        #  - full quest name case-insensitive substring (≥4 chars to avoid common words)
        id_re = re.compile(rf"(?<![\w-]){re.escape(qid)}(?![\w-])")
        if (
            (f"`{qid}`" in body_lower)
            or id_re.search(body_lower)
            or (len(qname) >= 4 and qname.lower() in body_lower)
        ):
            hints.append(qid)
    return hints


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

    # Soft hint — does this plan look like it depends on an existing quest?
    # Logged only; never auto-writes (user-controlled signal).
    try:
        plan_text_for_hints = plan_path.read_text(encoding="utf-8", errors="ignore")
        hints = detect_depends_hint(plan_text_for_hints, plan_path, project, quest["id"])
        if hints:
            log_msg(f"HINT {project_id}/{quest['id']}: plan mentions existing quest(s) {hints} — "
                    f"add `> **Depends on**: {','.join(hints)}` to BLUF if sequential")
    except Exception as e:
        log_msg(f"WARN depends hint: {e}")

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
