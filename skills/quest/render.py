#!/usr/bin/env python3
"""quest renderer — zero-dep template engine.

Reads ~/.claude/quest/data/quests.json and renders themed HTML for each
project to ~/.claude/quest/site/<project>/<view>.html

Template syntax:
  {{var}}                     — html-escaped substitution (project scope)
  {{{var}}}                   — raw substitution (no escape, for SVG/HTML blobs)
  {{q.field}}                 — quest scope (only inside {{#each quests}})
  {{#each quests}}…{{/each}}  — repeat block per quest
  {{#if field}}…{{/if}}       — conditional block (truthy = renders)
  {{> partial-name}}          — include partial; theme dir first, then _shared/

Unmatched markers are left visible (never crashes).
"""

import datetime as dt
import html
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path.home() / ".claude"
DATA = ROOT / "quest" / "data" / "quests.json"
SITE = ROOT / "quest" / "site"
THEMES = ROOT / "skills" / "quest" / "themes"
RUN_DIR = ROOT / "quest" / "run"

VIEWS = ["route", "quest-log", "plan-card"]


def _scan_live_claims() -> dict:
    """Walk ~/.claude/quest/run/*.quest. For each claim file whose pid is still
    alive (and ticks match — guards against pid reuse), read the .name sidecar
    if present. Returns: {(project_id, quest_id): [{name, pid}, ...]}.

    Dead claim files (process exited) are silently skipped. Sidecar absence is
    fine — claim still counts, name is None."""
    out: dict[tuple, list] = {}
    if not RUN_DIR.exists():
        return out
    for claim_file in RUN_DIR.glob("session-*.quest"):
        stem = claim_file.stem  # e.g. session-3249-3487
        try:
            _, pid_s, ticks_s = stem.split("-", 2)
            pid = int(pid_s)
        except (ValueError, AttributeError):
            continue
        # Verify process alive AND ticks match (pid-reuse guard)
        try:
            stat_path = Path(f"/proc/{pid}/stat")
            if not stat_path.exists():
                continue
            raw = stat_path.read_text()
            # Strip the (comm) field which can contain spaces / parens
            after = raw.split(")", 1)[1].strip() if ")" in raw else raw
            cur_ticks = after.split()[19]  # field 22, 0-indexed after comm strip
            if cur_ticks != ticks_s:
                continue
        except Exception:
            continue
        # Parse claim
        try:
            claim_txt = claim_file.read_text().strip()
            project_id, quest_id = claim_txt.split("/", 1)
        except Exception:
            continue
        # Read optional sidecar name
        name = None
        sidecar = claim_file.with_suffix(".name")
        if sidecar.exists():
            try:
                n = sidecar.read_text().strip()
                if n:
                    name = n
            except Exception:
                pass
        out.setdefault((project_id, quest_id), []).append({"name": name, "pid": pid})
    return out

# Quest fields that should be visible at project scope when rendering a plan-card
# block for that quest (so partials like _taskslist can reference {{tasks}} etc.).
HOISTED_QUEST_FIELDS = (
    "tasks", "tasks_done", "tasks_total", "tasks_next",
    "tasks_user", "tasks_user_done", "tasks_user_total", "tasks_user_next",
    "actions", "actions_done", "actions_total", "actions_next", "actions_next3", "actions_empty",
    "actions_user", "actions_user_done", "actions_user_total", "actions_user_next", "actions_user_next3", "actions_user_empty",
    "branch", "last_commit",
    "last_touched", "last_touched_human", "why", "blockers_str",
    "tags_str", "tags_pretty", "kpi", "depends_on", "depends_on_str", "depends_on_html",
    "successors_str", "successors_html", "plans_html", "plans_count",
    "dep_blocked",
    "links", "link_buckets", "effort", "problem", "solution",
    "next_step_problem", "next_step_solution",
    # 2026-05-13 schema additions for AI-resume briefings
    "resume_context", "files_touched", "commands", "gotchas", "repo",
    "briefing_md",  # built server-side; raw-injected into hidden <pre>
    "live_claims", "live_claims_html", "has_live_claims",  # render-time scan
)


def load_data() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def discover_themes() -> dict:
    themes = {}
    if not THEMES.exists():
        return themes
    for theme_dir in sorted(THEMES.iterdir()):
        meta = theme_dir / "theme.json"
        if meta.exists():
            try:
                themes[theme_dir.name] = json.loads(meta.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                print(f"WARN: theme.json unparseable in {theme_dir.name}: {exc}", file=sys.stderr)
    return themes


def load_template(theme: str, view: str) -> str:
    p = THEMES / theme / f"{view}.html.tmpl"
    if not p.exists():
        return f"<!-- missing template: themes/{theme}/{view}.html.tmpl -->"
    return p.read_text(encoding="utf-8")


def load_landmark(theme: str, kind: str) -> str:
    p = THEMES / theme / "landmarks" / f"{kind}.svg.tmpl"
    if not p.exists():
        return f"<!-- missing landmark: {theme}/{kind} -->"
    return p.read_text(encoding="utf-8")


def roman(n: int) -> str:
    table = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
             "XI", "XII", "XIII", "XIV", "XV"]
    return table[n] if 0 <= n < len(table) else str(n)


def humanize_iso(iso_str: str) -> str:
    """Return short human form: 'today', 'yesterday', '3d ago', '2026-04-21'.
    Returns empty string if unparseable — partial then renders blank row."""
    if not iso_str:
        return ""
    try:
        ts = dt.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        now = dt.datetime.now(dt.timezone.utc)
        delta = now - ts
        secs = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        if secs < 86400 * 2:
            return "yesterday"
        if secs < 86400 * 7:
            return f"{secs // 86400}d ago"
        if secs < 86400 * 30:
            return f"{secs // (86400 * 7)}w ago"
        return ts.strftime("%Y-%m-%d")
    except Exception:
        return ""


def precompute(project_id: str, project: dict, theme_meta: dict, live_claims_map: dict | None = None) -> dict:
    """Add derived fields used by templates. Mutates and returns project."""
    project["id"] = project_id

    # Status counts
    quests = project["quests"]
    project["counts"] = {
        "done": sum(1 for q in quests if q["status"] == "done"),
        "current": sum(1 for q in quests if q["status"] == "current"),
        "locked": sum(1 for q in quests if q["status"] == "locked"),
        "total": len(quests),
    }

    # Per-level XP percent
    xp = project.get("xp", {"current": 0, "max": 100})
    project["xp"] = xp
    project["xp_pct"] = int(100 * xp["current"] / xp["max"]) if xp.get("max") else 0
    project["level_roman"] = roman(project.get("level", 1))

    # Active quest summary (for footer / current display)
    active = next((q for q in quests if q["status"] == "current"), None)
    project["active"] = active or {"name": "", "next_step": "", "progress": 0, "n": 0}
    project["active_progress_pct"] = int(100 * project["active"].get("progress", 0))

    theme = project.get("theme", "pokemon")
    positions = (theme_meta.get(theme, {}) or {}).get("positions", {})

    # Build id→quest map first (needed for depends_on resolution per quest)
    by_id = {q.get("id", ""): q for q in quests}

    # Categorize each link by URL pattern. Bucket order = display order.
    _BUCKET_ORDER = ["Try it", "Code & commits", "Learning entries", "Project rules", "Skills", "Plan"]

    def _categorize_link(url: str) -> str:
        u = (url or "").lower()
        if "/.claude/skills/" in u or "/claude/skills/" in u:
            return "Skills"
        if "/.claude/rules/" in u or "/claude/rules/" in u:
            return "Project rules"
        if "/.claude/plans/" in u or "i-want-to-plan-" in u:
            return "Plan"
        if "memory-bank/learned/entry-" in u or "/data/audit/" in u:
            return "Learning entries"
        if "github.com" in u and ("/commit/" in u or "/pull/" in u or "/blob/" in u):
            return "Code & commits"
        return "Try it"

    def _build_link_buckets(links: list) -> list:
        grouped: dict[str, list] = {name: [] for name in _BUCKET_ORDER}
        for link in links:
            grouped[_categorize_link(link.get("url", ""))].append(link)
        out = []
        for name in _BUCKET_ORDER:
            items = grouped[name]
            if not items:
                continue
            # Pre-render <li> rows since template engine doesn't support nested {{#each}}.
            rows = []
            for li in items:
                label = html.escape(li.get("label") or li.get("url") or "")
                desc = html.escape(li.get("desc") or "")
                url = html.escape(li.get("url") or "", quote=True)
                desc_html = f'<span class="qd-link-desc">{desc}</span>' if desc else ""
                rows.append(
                    f'<li class="qd-link"><a class="qd-link-anchor" href="{url}" '
                    f'target="_blank" rel="noopener">'
                    f'<span class="qd-link-label">{label}</span>{desc_html}</a></li>'
                )
            out.append({"name": name, "count": len(items), "links_html": "".join(rows)})
        return out

    def _build_briefing_md(q: dict, proj_id: str) -> str:
        """Build a plain-text markdown briefing for a fresh AI / human reader.
        Empty sections are omitted. Output is plain text (no HTML escaping)."""
        out: list[str] = []
        n = q.get("n", "?")
        name = q.get("name") or q.get("id", "?")
        out.append(f"# Quest {n} · {name}")
        out.append("")
        # Status line
        meta_parts = [f"**Project**: {proj_id}"]
        sp = q.get("status_pretty")
        if sp:
            meta_parts.append(f"**Status**: {sp}")
        prog = q.get("progress")
        if isinstance(prog, (int, float)) and prog > 0:
            meta_parts.append(f"**Progress**: {int(prog * 100)}%")
        br = q.get("branch")
        if br:
            meta_parts.append(f"**Branch**: {br}")
        xp = q.get("xp_reward")
        if xp:
            meta_parts.append(f"**Reward**: +{xp} XP")
        out.append(" · ".join(meta_parts))
        out.append("")

        if q.get("desc"):
            out.append("## What this is")
            out.append("")
            out.append(q["desc"])
            out.append("")
        if q.get("why"):
            out.append("## Why it matters")
            out.append("")
            out.append(q["why"])
            out.append("")
        if q.get("kpi"):
            out.append('## Outcome that means "done"')
            out.append("")
            out.append(q["kpi"])
            out.append("")

        # Actions — done first, then todo. Accept dict or string entries.
        actions = q.get("actions") or []
        actions = [a for a in actions if isinstance(a, dict)]
        if actions:
            def _is_done(a: dict) -> bool:
                return (
                    a.get("status") in ("done", "DONE")
                    or a.get("status_class") == "done"
                    or a.get("done") is True
                )
            done = [a for a in actions if _is_done(a)]
            todo = [a for a in actions if not _is_done(a)]
            total = len(actions)
            if done:
                out.append(f"## Done so far ({len(done)} of {total})")
                out.append("")
                for a in done:
                    title = a.get("title") or ""
                    out.append(f"- {title}")
                out.append("")
            if todo:
                out.append(f"## Next steps ({len(todo)} to do)")
                out.append("")
                for i, a in enumerate(todo, 1):
                    title = a.get("title") or ""
                    out.append(f"{i}. {title}")
                out.append("")
        elif q.get("next_step"):
            out.append("## Next step")
            out.append("")
            out.append(q["next_step"])
            out.append("")

        if q.get("resume_context"):
            out.append("## Resume context")
            out.append("")
            out.append(q["resume_context"])
            out.append("")

        if q.get("repo"):
            out.append("## Repo")
            out.append("")
            out.append(f"`{q['repo']}`")
            out.append("")

        files = q.get("files_touched") or []
        if files:
            out.append("## Files touched")
            out.append("")
            for f in files:
                if f.get("role"):
                    out.append(f"- `{f['path']}` — {f['role']}")
                else:
                    out.append(f"- `{f['path']}`")
            out.append("")

        cmds = q.get("commands") or []
        if cmds:
            out.append("## Commands")
            out.append("")
            for c in cmds:
                if c.get("purpose"):
                    out.append(f"- `{c['cmd']}` — {c['purpose']}")
                else:
                    out.append(f"- `{c['cmd']}`")
            out.append("")

        gotchas = q.get("gotchas") or []
        if gotchas:
            out.append("## Gotchas (don't repeat)")
            out.append("")
            for g in gotchas:
                out.append(f"- {g}")
            out.append("")

        # Links: flatten buckets back to a short markdown list
        buckets = q.get("link_buckets") or []
        if buckets:
            out.append("## Links")
            out.append("")
            for bucket in buckets:
                out.append(f"**{bucket['name']}**")
                # links_html is HTML; pull from original list instead
            for link in (q.get("links") or []):
                lbl = link.get("label") or link.get("url", "")
                u = link.get("url", "")
                desc = link.get("desc", "")
                if desc:
                    out.append(f"- [{lbl}]({u}) — {desc}")
                else:
                    out.append(f"- [{lbl}]({u})")
            out.append("")

        lc = q.get("last_commit") or {}
        if lc.get("sha"):
            out.append(f"_Last commit: `{lc['sha']}` — {lc.get('msg', '')}_")

        return "\n".join(out).rstrip() + "\n"

    # Per-quest derivations
    for q in quests:
        status = q.get("status", "locked")
        q["status_class"] = status
        q["status_pretty"] = {"current": "Active", "done": "Visited", "locked": "Sealed"}.get(
            status, status.title()
        )
        # Boolean flags so templates can {{#if active.is_current}} pick the right
        # icon partial — the partial system can't pick by string value.
        q["is_current"] = status == "current"
        q["is_done"]    = status == "done"
        q["is_locked"]  = status == "locked"
        # Display title — "Quest Name (session-name)" when a session has claimed
        # this quest with a label that differs from the quest id. Last-claimer
        # wins (rare collision). Empty/no-claim → just the quest name.
        sname = (q.get("claimed_session_name") or "").strip()
        if sname:
            kebab = re.sub(r"[^a-z0-9]+", "-", sname.lower()).strip("-")
            if kebab and kebab != q.get("id", ""):
                q["display_name"] = f"{q.get('name', '')} ({sname})"
                q["session_name_suffix"] = sname
            else:
                q["display_name"] = q.get("name", "")
        else:
            q["display_name"] = q.get("name", "")
        q["progress_pct"] = int(100 * q.get("progress", 0))
        q["xp_str"] = f"+{q.get('xp_reward', 25)} XP"
        q["roman"] = roman(q.get("n", 0))
        q["landmark_svg"] = load_landmark(theme, q.get("landmark", "house"))
        # Position (transform attr) per quest n; defaults to (0,0) if missing
        q["transform"] = positions.get(str(q.get("n", "")), "translate(0,0)")
        # next_step shown only if non-empty + status==current
        q["has_next"] = bool(q.get("next_step")) and q.get("status") == "current"

        # Auto-size the quest label rect/path so long names don't overflow.
        # Width formula: max(80, char_count * 7 + 18). The +8 buffer covers
        # the "{n} · " or "{roman} · " prefix that varies between themes.
        name_chars = len(q.get("name", "")) + 8
        label_w = max(80, name_chars * 7 + 18)
        q["label_width"] = label_w
        q["label_x"] = -label_w // 2
        # For storybook's trapezoid label, inner-edge inset (creates lean shape).
        q["label_half"] = label_w // 2
        q["label_half_inner"] = max(label_w // 2 - 6, 6)

        # v2 schema derivations (all optional; absent fields stay absent)
        tasks = q.get("tasks", [])
        if tasks:
            for t in tasks:
                t["done_class"] = "done" if t.get("done") else "todo"
                t["done_mark"] = "✓" if t.get("done") else "○"
                # Click-to-expand markers — needs explicit truthy field per
                # {{#if}} (no {{#unless}}). Brief = problem OR solution OR plain brief.
                if t.get("problem") or t.get("solution") or t.get("brief"):
                    t["has_brief"] = True
                else:
                    t["no_brief"] = True
            q["tasks_done"] = sum(1 for t in tasks if t.get("done"))
            q["tasks_total"] = len(tasks)
            # First not-done task title — used as collapsed-summary preview
            next_task = next((t for t in tasks if not t.get("done")), None)
            if next_task:
                title = next_task.get("title", "")
                q["tasks_next"] = title[:80] + ("…" if len(title) > 80 else "")
        # Rich action items (new format — `### N. Title [STATUS]` from §13/§14).
        # Two parallel arrays: actions (Claude's actions) + actions_user (Yatir's).
        # Each item has {n, title, status, status_class, body_html}.
        # SYNTHESIS: legacy quests with tasks[] but no actions[] get auto-converted
        # so the rich UI shows for ALL quests. Synthesised actions have:
        #   - title from task title
        #   - status TODO/DONE based on done bool
        #   - body_html from problem/solution/brief sub-bullets if present
        # When synthesis fires, the legacy tasks/_taskslist section is suppressed
        # in _quest_scope to avoid duplicate rendering.
        if q.get("tasks") and not q.get("actions"):
            synth = []
            for i, t in enumerate(q["tasks"], start=1):
                done = bool(t.get("done"))
                body_parts = []
                if t.get("problem"):
                    body_parts.append(f"<p><strong>Problem:</strong> {html.escape(t['problem'])}</p>")
                if t.get("solution"):
                    body_parts.append(f"<p><strong>Solution:</strong> {html.escape(t['solution'])}</p>")
                if t.get("brief") and not (t.get("problem") or t.get("solution")):
                    body_parts.append(f"<p>{html.escape(t['brief'])}</p>")
                # Tasks may use either "title" (new) or "label" (legacy schema) —
                # accept both so synthesized actions never render with empty titles.
                title = t.get("title") or t.get("label") or ""
                synth.append({
                    "n": i,
                    "title": str(title)[:200],
                    "status": "DONE" if done else "TODO",
                    "status_class": "done" if done else "todo",
                    "body_html": "".join(body_parts),
                })
            q["actions"] = synth
            q["actions_synthesized"] = True  # signals to _quest_scope to drop legacy `tasks`

        if q.get("tasks_user") and not q.get("actions_user"):
            synth = []
            for i, t in enumerate(q["tasks_user"], start=1):
                done = bool(t.get("done"))
                body_parts = []
                if t.get("problem"):
                    body_parts.append(f"<p><strong>Problem:</strong> {html.escape(t['problem'])}</p>")
                if t.get("solution"):
                    body_parts.append(f"<p><strong>Solution:</strong> {html.escape(t['solution'])}</p>")
                if t.get("brief") and not (t.get("problem") or t.get("solution")):
                    body_parts.append(f"<p>{html.escape(t['brief'])}</p>")
                title = t.get("title") or t.get("label") or ""
                synth.append({
                    "n": i,
                    "title": str(title)[:200],
                    "status": "DONE" if done else "TODO",
                    "status_class": "done" if done else "todo",
                    "body_html": "".join(body_parts),
                })
            q["actions_user"] = synth
            q["actions_user_synthesized"] = True

        # Empty-state flags — when one side has actions but the other doesn't,
        # the missing section's empty-state placeholder renders so authors
        # discover §14 / §13 conventions for the next plan revision.
        has_cc = bool(q.get("actions"))
        has_user = bool(q.get("actions_user"))
        if has_cc and not has_user:
            q["actions_user_empty"] = True
        if has_user and not has_cc:
            q["actions_empty"] = True

        for arr_name, count_prefix in (("actions", "actions"), ("actions_user", "actions_user")):
            arr = q.get(arr_name, [])
            # Defensive: legacy data may have string entries; coerce to dict shape
            arr = [a if isinstance(a, dict) else {"title": str(a), "status_class": "todo"} for a in arr]
            if arr:
                q[f"{count_prefix}_done"] = sum(1 for a in arr if a.get("status_class") == "done")
                q[f"{count_prefix}_total"] = len(arr)
                # First not-done action title — single-line summary preview
                not_done = [a for a in arr if a.get("status_class") != "done"]
                if not_done:
                    title = not_done[0].get("title", "")
                    q[f"{count_prefix}_next"] = title[:80] + ("…" if len(title) > 80 else "")
                # Next 3 not-done items — compact peek list shown inside the
                # collapsed <summary>. Shallow copies with truncated titles so
                # the peek view never wraps awkwardly.
                next3 = []
                for a in not_done[:3]:
                    title = a.get("title", "")
                    next3.append({
                        "n": a.get("n"),
                        "title": title[:90] + ("…" if len(title) > 90 else ""),
                        "status": a.get("status", ""),
                        "status_class": a.get("status_class", "default"),
                    })
                if next3:
                    q[f"{count_prefix}_next3"] = next3
        # User-actor tasks (legacy §14 checkbox; preserved for back-compat)
        user_tasks = q.get("tasks_user", [])
        if user_tasks:
            for t in user_tasks:
                t["done_class"] = "done" if t.get("done") else "todo"
                t["done_mark"] = "✓" if t.get("done") else "○"
                if t.get("problem") or t.get("solution") or t.get("brief"):
                    t["has_brief"] = True
                else:
                    t["no_brief"] = True
            q["tasks_user_done"] = sum(1 for t in user_tasks if t.get("done"))
            q["tasks_user_total"] = len(user_tasks)
            next_user = next((t for t in user_tasks if not t.get("done")), None)
            if next_user:
                title = next_user.get("title", "")
                q["tasks_user_next"] = title[:80] + ("…" if len(title) > 80 else "")
        # Human-readable last-touched timestamp
        if q.get("last_touched"):
            q["last_touched_human"] = humanize_iso(q["last_touched"])
        # Normalize links: legacy string entries → {url, label, desc} objects.
        # Some quests stored bare path strings; template expects dict shape.
        raw_links = q.get("links")
        if isinstance(raw_links, list) and raw_links:
            norm = []
            for link in raw_links:
                if isinstance(link, dict):
                    norm.append({
                        "url": str(link.get("url", "")),
                        "label": str(link.get("label") or link.get("url") or ""),
                        "desc": str(link.get("desc", "")),
                        "source": link.get("source", ""),
                    })
                elif isinstance(link, str) and link.strip():
                    norm.append({"url": link, "label": link, "desc": "", "source": ""})
            q["links"] = norm
            # Group links into buckets by URL pattern. Empty buckets dropped.
            q["link_buckets"] = _build_link_buckets(norm)
        # Joined string fields (templates need pre-joined for {{#if}} truthiness)
        if q.get("blockers"):
            q["blockers_str"] = ", ".join(q["blockers"])
        if q.get("tags"):
            q["tags_str"] = ", ".join(q["tags"])
            # Human-readable: hyphens in tag tokens → spaces, joined with " · ".
            q["tags_pretty"] = " · ".join(t.replace("-", " ") for t in q["tags"])

        # ---- 2026-05-13 NEW FIELDS — normalize and render-friendly forms ----
        # files_touched: accept "path" string or {path, role} dict.
        raw_files = q.get("files_touched")
        if isinstance(raw_files, list) and raw_files:
            norm_files = []
            for entry in raw_files:
                if isinstance(entry, dict) and entry.get("path"):
                    norm_files.append({
                        "path": str(entry["path"]),
                        "role": str(entry.get("role", "")),
                    })
                elif isinstance(entry, str) and entry.strip():
                    norm_files.append({"path": entry.strip(), "role": ""})
            q["files_touched"] = norm_files

        # commands: accept "cmd" string or {cmd, purpose} dict.
        raw_cmds = q.get("commands")
        if isinstance(raw_cmds, list) and raw_cmds:
            norm_cmds = []
            for entry in raw_cmds:
                if isinstance(entry, dict) and entry.get("cmd"):
                    norm_cmds.append({
                        "cmd": str(entry["cmd"]),
                        "purpose": str(entry.get("purpose", "")),
                    })
                elif isinstance(entry, str) and entry.strip():
                    norm_cmds.append({"cmd": entry.strip(), "purpose": ""})
            q["commands"] = norm_cmds

        # gotchas: list of plain strings, "don't try X — already failed" notes.
        raw_gotchas = q.get("gotchas")
        if isinstance(raw_gotchas, list) and raw_gotchas:
            q["gotchas"] = [str(g).strip() for g in raw_gotchas if str(g).strip()]

        # resume_context: paragraph for fresh AI session. No normalization beyond strip.
        if isinstance(q.get("resume_context"), str):
            q["resume_context"] = q["resume_context"].strip()

        # repo: absolute path string.
        if isinstance(q.get("repo"), str):
            q["repo"] = q["repo"].strip()
        # Attach live claims for this quest (computed once per render_all).
        if live_claims_map is not None:
            claims = live_claims_map.get((project_id, q.get("id", "")), [])
            if claims:
                q["live_claims"] = claims
                q["has_live_claims"] = True
                pills = []
                for c in claims:
                    name = (c.get("name") or "").strip() or f"pid {c.get('pid')}"
                    pills.append(
                        f'<span class="qd-live-claim-pill">{html.escape(name)}</span>'
                    )
                q["live_claims_html"] = "".join(pills)

        # Build briefing markdown for the Copy-briefing button + .md endpoint.
        # Must run AFTER all normalizations above so it captures the final shape.
        q["briefing_md"] = _build_briefing_md(q, project_id)
        # ---- end new-fields normalization ----
        # Next-step expandable marker
        if q.get("next_step") and not q.get("next_step_problem"):
            q["no_next_brief"] = True
        # Sequential dependency hints — resolve quest-id → "#N name"
        deps = q.get("depends_on") or []
        if deps:
            resolved = []
            html_parts = []
            for did in deps:
                dq = by_id.get(did)
                if dq:
                    label = f"#{dq.get('n','?')} {dq.get('name','?')}"
                    resolved.append(label)
                    href = f"plan-card.html?q={html.escape(did, quote=True)}"
                    html_parts.append(
                        f'<a class="qd-storyline-link" href="{href}">'
                        f'{html.escape(label, quote=True)}</a>'
                    )
                else:
                    resolved.append(did)
                    html_parts.append(html.escape(did, quote=True))
            q["depends_on_str"] = ", ".join(resolved)
            q["depends_on_html"] = (
                '<span class="qd-storyline-arrow" aria-hidden="true">◀ </span>'
                + " · ".join(html_parts)
            )
            # Locked-by-dep marker: only if status is locked AND any dep is incomplete
            unmet = [by_id.get(d) for d in deps if by_id.get(d)]
            if unmet and any((dq.get("status") != "done") for dq in unmet) and q.get("status") == "locked":
                q["dep_blocked"] = True

        # Successors — reverse lookup: quests that list THIS quest in their depends_on.
        my_id = q.get("id", "")
        successors = []
        if my_id:
            for other in quests:
                if other is q:
                    continue
                if my_id in (other.get("depends_on") or []):
                    successors.append(other)
        if successors:
            labels = [f"#{s.get('n','?')} {s.get('name','?')}" for s in successors]
            q["successors_str"] = ", ".join(labels)
            s_parts = []
            for s in successors:
                label = f"#{s.get('n','?')} {s.get('name','?')}"
                href = f"plan-card.html?q={html.escape(s.get('id',''), quote=True)}"
                s_parts.append(
                    f'<a class="qd-storyline-link" href="{href}">'
                    f'{html.escape(label, quote=True)}</a>'
                )
            q["successors_html"] = (
                " · ".join(s_parts)
                + ' <span class="qd-storyline-arrow" aria-hidden="true">▶</span>'
            )

        # Plan files — originating `plan` (singular, autosync-set) + optional
        # `plans` array of sub-plans (manually edited or future autosync).
        # Normalize plan paths to filename only — strips ~/.claude/plans/ and
        # /home/<user>/.claude/plans/ absolute prefixes so the chip shows just
        # the filename and the inline "Plan file: ~/.claude/plans/<name>" line
        # doesn't double-concat the prefix.
        def _plan_filename(raw: str) -> str:
            s = str(raw or "").strip()
            for prefix in ("~/.claude/plans/", "~/.claude/plans"):
                if s.startswith(prefix):
                    s = s[len(prefix):].lstrip("/")
            for prefix in ("/.claude/plans/", "/.claude/plans"):
                idx = s.find(prefix)
                if idx >= 0:
                    s = s[idx + len(prefix):].lstrip("/")
            return s

        plan_files = []
        seen = set()
        if q.get("plan"):
            normalized = _plan_filename(q["plan"])
            q["plan"] = normalized  # propagate cleaned form to template
            if normalized:
                plan_files.append(normalized)
                seen.add(normalized)
        for p in (q.get("plans") or []):
            np = _plan_filename(p)
            if np and np not in seen:
                plan_files.append(np)
                seen.add(np)
        if plan_files:
            chips = [
                f'<code class="qd-plan-chip">{html.escape(p, quote=True)}</code>'
                for p in plan_files
            ]
            q["plans_html"] = " ".join(chips)
            q["plans_count"] = len(plan_files)

    # Hoist FIRST-current quest's v2 fields onto project scope. Used by route +
    # quest-log views (which still render against project scope). Plan-card no
    # longer relies on this hoist — render_project builds per-quest scopes via
    # _quest_scope() so each quest's plan-card block sees its own data.
    if active:
        for k in HOISTED_QUEST_FIELDS:
            if k in active:
                project[k] = active[k]
        project["progress_pct"] = int(100 * active.get("progress", 0))

    # Chapter list (past adventures) — only set if non-empty
    chapters = project.get("chapters") or {}
    if chapters:
        project["chapters_list"] = [
            {"name": name, "count": len(quests_in)}
            for name, quests_in in chapters.items() if quests_in
        ]
        project["has_chapters"] = bool(project["chapters_list"])

    return project


# ---- substitution engine ----

# Match {{{path}}} (raw) and {{path}} (escaped). Order matters: triple first.
# {{path}} excludes leading #, /, >, { to avoid catching block / partial markers.
_TRIPLE = re.compile(r"\{\{\{([^{}]+?)\}\}\}")
_DOUBLE = re.compile(r"\{\{([^#/>{}][^{}]*?)\}\}")
_EACH = re.compile(r"\{\{#each\s+([\w.]+)\}\}(.*?)\{\{/each\}\}", re.DOTALL)
# Tempered-token body excludes nested {{#if so inner ifs match first.
# The while-loop in _expand_if then peels outer layers.
_IF = re.compile(r"\{\{#if\s+([\w.]+)\}\}((?:(?!\{\{#if\s).)*?)\{\{/if\}\}", re.DOTALL)
_PARTIAL = re.compile(r"\{\{>\s*([\w./-]+)\s*\}\}")


def _truthy(val) -> bool:
    """Match Python truthiness, excluding the bare-marker fallback string."""
    if val is None or val is False:
        return False
    if isinstance(val, str):
        # _resolve returns "{{path}}" when unresolved — treat as falsy
        if val.startswith("{{") and val.endswith("}}"):
            return False
        return bool(val.strip())
    if isinstance(val, (list, dict)):
        return len(val) > 0
    return bool(val)


def _resolve_value(path: str, scope: dict):
    """Like _resolve but returns the raw value (for {{#if}} truthiness)."""
    parts = path.strip().split(".")
    obj = scope
    for part in parts:
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return None
    return obj


def _expand_partials(template: str, theme: str) -> str:
    """Inline {{> partial-name}}. Theme dir first, then _shared/. Leaves marker
    visible if not found (debug-friendly). Recursive (partials include partials)."""
    def replace(m: re.Match) -> str:
        name = m.group(1).strip()
        # Try theme-specific override, then shared
        for candidate in (THEMES / theme / f"{name}.html.tmpl",
                          THEMES / "_shared" / f"{name}.html.tmpl"):
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        return f"<!-- missing partial: {name} -->"

    prev = None
    while prev != template:
        prev = template
        template = _PARTIAL.sub(replace, template)
    return template


def _expand_if(template: str, scope: dict) -> str:
    """Render {{#if path}}…{{/if}} only when path resolves to truthy."""
    def replace(m: re.Match) -> str:
        path = m.group(1)
        block = m.group(2)
        return block if _truthy(_resolve_value(path, scope)) else ""

    prev = None
    while prev != template:
        prev = template
        template = _IF.sub(replace, template)
    return template


def _resolve(path: str, scope: dict) -> str:
    """Walk dotted path through nested dicts. Returns stringified value or
    the original {{path}} marker if unresolved (visible bug indicator)."""
    parts = path.strip().split(".")
    obj = scope
    for part in parts:
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return "{{" + path.strip() + "}}"  # leave visible
    if obj is None:
        return ""
    return str(obj)


def _sub_pass(template: str, scope: dict) -> str:
    """Apply {{{raw}}} then {{escaped}} substitutions in scope."""
    template = _TRIPLE.sub(lambda m: _resolve(m.group(1), scope), template)
    template = _DOUBLE.sub(
        lambda m: html.escape(_resolve(m.group(1), scope), quote=True),
        template,
    )
    return template


def _expand_each(template: str, scope: dict) -> str:
    """Expand {{#each path}}…{{/each}} blocks."""
    def replace(m: re.Match) -> str:
        path = m.group(1)
        block = m.group(2)
        items = scope
        for part in path.split("."):
            if isinstance(items, dict) and part in items:
                items = items[part]
            else:
                items = []
                break
        if not isinstance(items, list):
            return ""
        out = []
        theme = scope.get("theme", "pokemon")
        for item in items:
            inner_scope = {**scope, "q": item}
            out.append(_render(block, inner_scope, theme))
        return "".join(out)

    # Repeat until no more {{#each}} (handles non-nested cases)
    prev = None
    while prev != template:
        prev = template
        template = _EACH.sub(replace, template)
    return template


def _render(template: str, scope: dict, theme: str = "pokemon") -> str:
    """Full render order: partials → each-blocks → if-blocks → vars.
    Partials run first so their content participates in each/if/var passes.
    Each runs before if so {{q.field}} truthiness inside loop bodies works."""
    template = _expand_partials(template, theme)
    template = _expand_each(template, scope)
    template = _expand_if(template, scope)
    template = _sub_pass(template, scope)
    return template


# ---- top-level rendering ----


def _quest_scope(project: dict, q: dict) -> dict:
    """Build a render scope for ONE quest's plan-card block. Project-level
    fields stay accessible; `active` is set to this quest; v2 fields hoist
    from this quest onto the scope so partials like _taskslist resolve.
    Does NOT mutate `project`."""
    scope = dict(project)
    scope["active"] = q
    scope["active_progress_pct"] = int(100 * q.get("progress", 0))
    # First, drop ALL hoisted fields from project scope so this quest's block
    # doesn't accidentally inherit the first-current quest's data.
    for k in HOISTED_QUEST_FIELDS:
        scope.pop(k, None)
    # Then, hoist THIS quest's fields onto the scope.
    for k in HOISTED_QUEST_FIELDS:
        if k in q:
            scope[k] = q[k]
    # When actions[] was synthesized from tasks[], drop tasks from scope so the
    # legacy _taskslist partial doesn't render a duplicate "Deeds" section.
    # Same for tasks_user.
    if q.get("actions_synthesized"):
        scope.pop("tasks", None)
        scope.pop("tasks_done", None)
        scope.pop("tasks_total", None)
        scope.pop("tasks_next", None)
    if q.get("actions_user_synthesized"):
        scope.pop("tasks_user", None)
        scope.pop("tasks_user_done", None)
        scope.pop("tasks_user_total", None)
        scope.pop("tasks_user_next", None)
    scope["progress_pct"] = int(100 * q.get("progress", 0))
    return scope


def _render_quest_blocks(project: dict, theme: str) -> tuple[str, str, str]:
    """Render the per-quest plan-card body N times — one per quest in the
    project. Each block is wrapped in <article class="qd-quest-block"
    data-quest-id="..."> so the outer plan-card.html JS can show/hide based
    on `?q=<id>`.

    Returns (quest_blocks_html, active_picker_html, default_quest_id_json).
    `default_quest_id_json` is a JSON-string literal for embedding in the
    JS dispatcher (always quoted, even when empty)."""
    body_tmpl_path = THEMES / theme / "_plan-card-quest.html.tmpl"
    if not body_tmpl_path.exists():
        return (
            f"<!-- missing per-quest body template: themes/{theme}/_plan-card-quest.html.tmpl -->",
            "",
            json.dumps(""),
        )
    body_tmpl = body_tmpl_path.read_text(encoding="utf-8")

    quests = project.get("quests", [])
    blocks: list[str] = []
    for q in quests:
        scope = _quest_scope(project, q)
        body = _render(body_tmpl, scope, theme)
        qid = q.get("id", "")
        qname = q.get("name", "")
        qn = q.get("n", "")
        blocks.append(
            f'<article class="qd-quest-block" '
            f'data-quest-id="{html.escape(qid, quote=True)}" '
            f'data-quest-name="{html.escape(str(qname), quote=True)}" '
            f'data-quest-n="{html.escape(str(qn), quote=True)}">'
            f"{body}</article>"
        )

    # Default = first current quest (matches original single-active behaviour).
    default_q = next((q for q in quests if q.get("status") == "current"), None) or (
        quests[0] if quests else None
    )
    default_qid = default_q.get("id", "") if default_q else ""

    # Active picker — only render if 2+ current quests exist (single-current is
    # the legacy case and doesn't need a picker bar).
    currents = [q for q in quests if q.get("status") == "current"]
    if len(currents) >= 2:
        items = []
        for q in currents:
            qid = html.escape(q.get("id", ""), quote=True)
            label = html.escape(f"#{q.get('n','?')} {q.get('name','?')}", quote=True)
            items.append(
                f'<a href="plan-card.html?q={qid}" data-qid="{qid}">{label}</a>'
            )
        picker = (
            '<nav class="qd-active-picker" aria-label="Active quests">'
            '<span class="qd-active-picker-label">'
            f'⚔ {len(currents)} active</span>'
            '<span class="qd-active-picker-list">'
            + "".join(items)
            + "</span></nav>"
        )
    else:
        picker = ""

    return "\n".join(blocks), picker, json.dumps(default_qid)


def render_project(project: dict, theme: str) -> dict:
    """Render all views for one project. Returns {view: html}.

    Plan-card is special-cased: rendered as an outer shell containing N
    per-quest blocks (one per quest in the project). The outer JS reads
    `?q=<id>` and toggles visibility — so all internal hrefs of the form
    `plan-card.html?q=<id>` resolve to the correct block on a single page."""
    out = {}
    for view in VIEWS:
        tmpl = load_template(theme, view)
        if view == "plan-card":
            blocks_html, picker_html, default_qid_json = _render_quest_blocks(project, theme)
            scope = dict(project)
            scope["quest_blocks_html"] = blocks_html
            scope["active_picker_html"] = picker_html
            scope["default_quest_json"] = default_qid_json
            out[view] = _render(tmpl, scope, theme)
        else:
            out[view] = _render(tmpl, project, theme)
    return out


# ---- Global home index (Trainer Hall) ----

# Default per-project accent + landmark icon. Both are overridable via
# `accent` / `icon` fields on a project in quests.json. Fallback when a project
# isn't in this map: rotate through ACCENT_PALETTE / ICON_ROTATION by index.
DEFAULT_ACCENTS: dict[str, str] = {
    "limor":    "#ff6a3a",
    "smith":    "#3aaa6a",
    "ogas":     "#9a6ace",
    "gamify":   "#e8b430",
    "logivote": "#3a8aa0",
    "remotion": "#c44a2a",
}
DEFAULT_ICONS: dict[str, str] = {
    "limor":    "house",
    "smith":    "camp",
    "ogas":     "castle",
    "gamify":   "camp",
    "logivote": "cave",
    "remotion": "tower",
}
ACCENT_PALETTE: list[str] = ["#ff6a3a", "#3aaa6a", "#9a6ace", "#e8b430", "#3a8aa0", "#c44a2a", "#5db4d8", "#ffd24a"]
ICON_ROTATION: list[str] = ["house", "camp", "castle", "cave", "tower", "bridge", "mill"]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def lighten(hex_color: str, factor: float = 0.5) -> str:
    """Mix toward white. factor=0 returns input; factor=1 returns white."""
    r, g, b = _hex_to_rgb(hex_color)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def precompute_global_index(data: dict) -> dict:
    """Build the scope passed to the global-index.html.tmpl template.

    Aggregates totals across projects + per-project derived fields (counts,
    accent, icon SVG, formatted active-quest label, route/log hrefs). The
    template renders 6 cards (or however many projects exist) in the
    Trainer Hall layout.
    """
    projects = data.get("projects", {})

    totals = {
        "levels": sum(p.get("level", 1) for p in projects.values()),
        "xp":     sum((p.get("xp") or {}).get("current", 0) for p in projects.values()),
        "done":   sum(sum(1 for q in p.get("quests", []) if q.get("status") == "done") for p in projects.values()),
        "active": sum(sum(1 for q in p.get("quests", []) if q.get("status") == "current") for p in projects.values()),
    }

    projects_list = []
    for n, (pid, p) in enumerate(projects.items(), start=1):
        quests = p.get("quests", [])
        counts = {
            "current": sum(1 for q in quests if q.get("status") == "current"),
            "done":    sum(1 for q in quests if q.get("status") == "done"),
            "locked":  sum(1 for q in quests if q.get("status") == "locked"),
        }
        currents = [q for q in quests if q.get("status") == "current"]
        active = currents[0] if currents else None
        theme = p.get("theme", "pokemon")
        xp = p.get("xp", {"current": 0, "max": 100})
        xp_max = xp.get("max", 100) or 100
        xp_pct = int(100 * xp.get("current", 0) / xp_max)

        # Accent + icon: project-declared field wins, then per-pid default,
        # else rotate through palette / icon list by index.
        accent = p.get("accent") or DEFAULT_ACCENTS.get(pid) or ACCENT_PALETTE[(n - 1) % len(ACCENT_PALETTE)]
        icon_kind = p.get("icon") or DEFAULT_ICONS.get(pid) or ICON_ROTATION[(n - 1) % len(ICON_ROTATION)]
        grass_dark = accent
        grass_light = lighten(accent, 0.55)

        # Borrow the icon from the project's own theme; fall back to pokemon
        # so the global index always renders even if a custom theme lacks it.
        icon_svg = load_landmark(theme, icon_kind)
        if icon_svg.startswith("<!-- missing landmark"):
            icon_svg = load_landmark("pokemon", icon_kind)

        # Active label — show first current. When multiple, append "+N more".
        if active:
            base = f"#{active.get('n','?')} {active.get('name','?')}"
            if len(currents) > 1:
                active_label = f"{base}  ·  +{len(currents) - 1} more"
            else:
                active_label = base
        else:
            active_label = ""
        # Full list of currents — used when home-index template wants to render
        # all (currently we just stuff first + count-suffix into active_label).
        actives_full = [
            {
                "id": q.get("id", ""),
                "n": q.get("n", "?"),
                "name": q.get("name", "?"),
                "label": f"#{q.get('n','?')} {q.get('name','?')}",
            }
            for q in currents
        ]

        projects_list.append({
            "id": pid,
            "n": n,
            "name": p.get("name", pid),
            "subtitle": p.get("subtitle") or "—",
            "level": p.get("level", 1),
            "xp_current": xp.get("current", 0),
            "xp_max": xp_max,
            "xp_pct": xp_pct,
            "theme": theme,
            "theme_label": "Storybook" if theme == "storybook" else "Pokémon",
            "strip_class": "storybook" if theme == "storybook" else "",
            "counts": counts,
            "has_active": active is not None,
            "no_active": active is None,
            "active_label": active_label,
            "actives": actives_full,
            "actives_count": len(currents),
            "accent": accent,
            "grass_dark": grass_dark,
            "grass_light": grass_light,
            "icon_kind": icon_kind,
            "icon_svg": icon_svg,
            "route_href": f"{pid}/route.html",
            "log_href": f"{pid}/quest-log.html",
        })

    return {"projects_list": projects_list, "totals": totals}


def render_global_index(data: dict) -> str:
    """Render the home page (Trainer Hall layout) — replaces the prior bullet list."""
    template_path = THEMES / "_shared" / "global-index.html.tmpl"
    if not template_path.exists():
        return f"<!-- missing template: {template_path} -->"
    template = template_path.read_text(encoding="utf-8")
    scope = precompute_global_index(data)
    # Theme arg controls partial resolution; this template doesn't use partials.
    return _render(template, scope, "pokemon")


def render_all() -> int:
    if not DATA.exists():
        print(f"ERROR: {DATA} does not exist. Run /quest init first.", file=sys.stderr)
        return 2

    data = load_data()
    themes = discover_themes()
    SITE.mkdir(parents=True, exist_ok=True)

    # Scan live claims once for the whole render pass (cheap, single proc walk).
    live_claims_map = _scan_live_claims()

    # Soft-warn for active quests missing the core fields. Doesn't block rendering.
    _missing = []
    for _pid, _proj in data["projects"].items():
        for _q in _proj.get("quests", []):
            if _q.get("status") != "current":
                continue
            gaps = [k for k in ("desc", "kpi", "why", "next_step") if not _q.get(k)]
            if gaps:
                _missing.append(f"{_pid}/#{_q.get('n','?')} {_q.get('id','?')}: missing {', '.join(gaps)}")
    if _missing:
        print("  WARN: active quests with missing core fields:", file=sys.stderr)
        for line in _missing[:20]:
            print(f"    - {line}", file=sys.stderr)
        if len(_missing) > 20:
            print(f"    ({len(_missing) - 20} more)", file=sys.stderr)

    rendered = 0
    md_written = 0
    for pid, project in data["projects"].items():
        precompute(pid, project, themes, live_claims_map=live_claims_map)
        proj_dir = SITE / pid
        proj_dir.mkdir(parents=True, exist_ok=True)
        for view, html_out in render_project(project, project.get("theme", "pokemon")).items():
            (proj_dir / f"{view}.html").write_text(html_out, encoding="utf-8")
        # Per-quest .md briefing files for AI/curl access. Two paths each:
        #   localhost:8770/<project>/quest-<id>.md  (prefixed, namespace-safe)
        #   localhost:8770/<project>/<id>.md        (shorter, friendlier)
        # Bare-name shadowing of theme files (plan-card, quest-log, route, index)
        # is impossible because those are .html, not .md.
        for q in project.get("quests", []):
            qid = q.get("id")
            md = q.get("briefing_md")
            if qid and md:
                (proj_dir / f"quest-{qid}.md").write_text(md, encoding="utf-8")
                (proj_dir / f"{qid}.md").write_text(md, encoding="utf-8")
                md_written += 1
        rendered += 1
        print(f"  rendered: {pid} ({project.get('theme')})")

    # Global index
    (SITE / "index.html").write_text(render_global_index(data), encoding="utf-8")

    print(f"OK — {rendered} project(s), {md_written} quest briefings rendered to {SITE}")
    return 0


def cli_main():
    if "--dry-run" in sys.argv:
        data = load_data()
        themes = discover_themes()
        print(f"data: {DATA}")
        print(f"projects: {list(data['projects'].keys())}")
        print(f"themes: {list(themes.keys())}")
        for pid, p in data["projects"].items():
            theme = p.get("theme", "pokemon")
            print(f"  {pid}: theme={theme}, quests={len(p['quests'])}, level={p.get('level',1)}")
        return 0
    return render_all()


if __name__ == "__main__":
    sys.exit(cli_main())
