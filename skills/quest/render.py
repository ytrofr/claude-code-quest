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

VIEWS = ["route", "quest-log", "plan-card"]


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


def precompute(project_id: str, project: dict, theme_meta: dict) -> dict:
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

    # Per-quest derivations
    for q in quests:
        q["status_class"] = q.get("status", "locked")
        q["progress_pct"] = int(100 * q.get("progress", 0))
        q["xp_str"] = f"+{q.get('xp_reward', 25)} XP"
        q["roman"] = roman(q.get("n", 0))
        q["landmark_svg"] = load_landmark(theme, q.get("landmark", "house"))
        # Position (transform attr) per quest n; defaults to (0,0) if missing
        q["transform"] = positions.get(str(q.get("n", "")), "translate(0,0)")
        # next_step shown only if non-empty + status==current
        q["has_next"] = bool(q.get("next_step")) and q.get("status") == "current"

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
        # Human-readable last-touched timestamp
        if q.get("last_touched"):
            q["last_touched_human"] = humanize_iso(q["last_touched"])
        # Joined string fields (templates need pre-joined for {{#if}} truthiness)
        if q.get("blockers"):
            q["blockers_str"] = ", ".join(q["blockers"])
        if q.get("tags"):
            q["tags_str"] = ", ".join(q["tags"])
        # Next-step expandable marker
        if q.get("next_step") and not q.get("next_step_problem"):
            q["no_next_brief"] = True

    # Hoist active quest's v2 fields onto project scope so plan-card partials
    # (which run at project scope) can reference {{tasks}}, {{branch}}, etc.
    if active:
        for k in ("tasks", "tasks_done", "tasks_total", "branch", "last_commit",
                  "last_touched", "last_touched_human", "why", "blockers_str",
                  "tags_str", "kpi", "depends_on", "links", "effort"):
            if k in active:
                project[k] = active[k]
        project["progress_pct"] = int(100 * active.get("progress", 0))

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
_PARTIAL = re.compile(r"\{\{>\s*([\w.-]+)\s*\}\}")


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


def render_project(project: dict, theme: str) -> dict:
    """Render all views for one project. Returns {view: html}."""
    out = {}
    for view in VIEWS:
        tmpl = load_template(theme, view)
        out[view] = _render(tmpl, project, theme)
    return out


def render_global_index(data: dict) -> str:
    """Tiny landing page listing all projects with links."""
    rows = []
    for pid, p in data["projects"].items():
        name = html.escape(p.get("name", pid))
        sub = html.escape(p.get("subtitle", ""))
        theme = html.escape(p.get("theme", "pokemon"))
        lvl = p.get("level", 1)
        xp = p.get("xp", {"current": 0, "max": 100})
        rows.append(
            f'<li><a href="{pid}/route.html"><strong>{name}</strong></a> '
            f'— <em>{sub}</em> · Lv {lvl} · {xp["current"]}/{xp["max"]} XP · '
            f'<span class="theme">{theme}</span> '
            f'(<a href="{pid}/quest-log.html">log</a>)</li>'
        )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Quest Dashboard</title>
<style>
body {{ font: 16px/1.5 system-ui, sans-serif; background: #faf3df; color: #3a2010; padding: 32px; }}
h1 {{ font-size: 28px; margin: 0 0 8px; }}
.sub {{ color: #6a4828; margin-bottom: 24px; }}
ul {{ list-style: none; padding: 0; }}
li {{ padding: 14px 18px; background: #fff; border: 2px solid #3a2010; border-radius: 10px; margin-bottom: 10px; box-shadow: 0 3px 0 #3a2010; }}
a {{ color: #c44a2a; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.theme {{ font-size: 12px; padding: 2px 8px; background: #ffd9b8; border-radius: 10px; }}
</style></head>
<body>
<h1>Quest Dashboard</h1>
<p class="sub">All projects at a glance. Source of truth: <code>~/.claude/quest/data/quests.json</code></p>
<ul>
{chr(10).join(rows)}
</ul>
</body></html>
"""


def render_all() -> int:
    if not DATA.exists():
        print(f"ERROR: {DATA} does not exist. Run /quest init first.", file=sys.stderr)
        return 2

    data = load_data()
    themes = discover_themes()
    SITE.mkdir(parents=True, exist_ok=True)

    rendered = 0
    for pid, project in data["projects"].items():
        precompute(pid, project, themes)
        proj_dir = SITE / pid
        proj_dir.mkdir(parents=True, exist_ok=True)
        for view, html_out in render_project(project, project.get("theme", "pokemon")).items():
            (proj_dir / f"{view}.html").write_text(html_out, encoding="utf-8")
        rendered += 1
        print(f"  rendered: {pid} ({project.get('theme')})")

    # Global index
    (SITE / "index.html").write_text(render_global_index(data), encoding="utf-8")

    print(f"OK — {rendered} project(s) rendered to {SITE}")
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
