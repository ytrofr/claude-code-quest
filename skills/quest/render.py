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

    # Build id→quest map first (needed for depends_on resolution per quest)
    by_id = {q.get("id", ""): q for q in quests}

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
        plan_files = []
        seen = set()
        if q.get("plan"):
            plan_files.append(q["plan"])
            seen.add(q["plan"])
        for p in (q.get("plans") or []):
            if p and p not in seen:
                plan_files.append(p)
                seen.add(p)
        if plan_files:
            chips = [
                f'<code class="qd-plan-chip">{html.escape(p, quote=True)}</code>'
                for p in plan_files
            ]
            q["plans_html"] = " ".join(chips)
            q["plans_count"] = len(plan_files)

    # Hoist active quest's v2 fields onto project scope so plan-card partials
    # (which run at project scope) can reference {{tasks}}, {{branch}}, etc.
    if active:
        for k in ("tasks", "tasks_done", "tasks_total", "branch", "last_commit",
                  "last_touched", "last_touched_human", "why", "blockers_str",
                  "tags_str", "kpi", "depends_on", "depends_on_str", "depends_on_html",
                  "successors_str", "successors_html", "plans_html", "plans_count",
                  "dep_blocked",
                  "links", "effort", "problem", "solution",
                  "next_step_problem", "next_step_solution"):
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
        active = next((q for q in quests if q.get("status") == "current"), None)
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

        active_label = f"#{active.get('n','?')} {active.get('name','?')}" if active else ""

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
