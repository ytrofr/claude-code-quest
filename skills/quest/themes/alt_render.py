#!/usr/bin/env python3
"""Alt-theme renderer for quest maps — solar + worldmap.

Reads ~/.claude/quest/data/quests.json and writes:
  ~/.claude/quest/site/<project>/route-solar.html      (cartoon solar systems)
  ~/.claude/quest/site/<project>/route-worldmap.html   (Pokemon worldmap, multi-region)

Both files include a 3-tab switcher banner [default · solar · worldmap] so users
can flip themes from any project map.

Usage:
  python3 ~/.claude/skills/quest/themes/alt_render.py                # all projects, both themes
  python3 ~/.claude/skills/quest/themes/alt_render.py --project=ogas # one project
  python3 ~/.claude/skills/quest/themes/alt_render.py --theme=solar  # one theme, all projects
  python3 ~/.claude/skills/quest/themes/alt_render.py --post-inject  # also inject switcher into existing route.html

Design invariants:
  - Zero edits to render.py (additive only)
  - Idempotent (rerun = overwrite)
  - Pure Python stdlib (no external deps)
  - Per-project clustering by tag, falling back to status buckets
"""

from __future__ import annotations
import argparse
import html as _html
import json
import sys
from pathlib import Path

ROOT = Path.home() / ".claude"
DATA = ROOT / "quest" / "data" / "quests.json"
SITE = ROOT / "quest" / "site"

# ============================================================
# CLUSTERING — tag-based with sensible fallbacks
# ============================================================

# Tag → cluster label. First match wins. Lowercase prefix match against any tag.
TAG_RULES = [
    (("layout-editor", "inline-editor", "mobile-ux", "viewport", "zoom", "tier1", "modularization"), "⚙ Layout Editor"),
    (("webgen", "moshytz", "phase-10", "phase10", "phase-6", "phase-9", "brand", "dna-mode", "inspiration"), "🌐 Web Generation"),
    (("kpi", "visual-qa", "visual", "qa", "anti-slop", "scoring", "ssim", "verdict", "fidelity"), "🔬 Visual QA & Scoring"),
    (("adk", "keyword-routing", "orchestrator", "agent", "binary-llm-judge", "tool", "creative-save"), "🛠 Agent / ADK"),
    (("plan", "quest", "session", "main-quest", "master-quest", "operator-action"), "📝 Plan / Quest"),
    (("auth", "oauth", "rotation", "security"), "🔐 Auth / Security"),
    (("hosting", "deploy", "cloud-run", "infrastructure"), "🚀 Hosting / Deploy"),
    (("cache", "firestore", "pgvector", "storage"), "💾 Storage / Cache"),
    (("hebrew", "rtl", "i18n"), "🌍 Hebrew / RTL"),
    (("brick-by-brick", "consolidated-mission", "long-running", "phase5-soak"), "🎯 Long-Running"),
]

# Name-keyword → cluster (fallback when no matching tags)
NAME_RULES = [
    (("layout", "editor", "modular", "inline"), "⚙ Layout Editor"),
    (("web", "moshytz", "clone", "dorian", "variant", "brand"), "🌐 Web Generation"),
    (("qa", "score", "visual", "verdict", "kpi", "fidelity", "anti-slop", "scoring"), "🔬 Visual QA & Scoring"),
    (("plan", "quest", "fuzzy", "create"), "📝 Plan / Quest"),
    (("auth", "oauth", "secret", "rotation"), "🔐 Auth / Security"),
    (("hosting", "deploy", "ship", "soak"), "🚀 Hosting / Deploy"),
    (("cache", "store", "firestore", "pgvector"), "💾 Storage / Cache"),
    (("agent", "adk", "tool", "creative", "save"), "🛠 Agent / ADK"),
]

# Cluster → biome (for worldmap region styling)
BIOME_MAP = {
    "⚙ Layout Editor":      "city",
    "🌐 Web Generation":     "plateau",
    "🔬 Visual QA & Scoring": "forest",
    "🛠 Agent / ADK":         "tower",
    "📝 Plan / Quest":        "lake",
    "🔐 Auth / Security":     "fortress",
    "🚀 Hosting / Deploy":    "harbor",
    "💾 Storage / Cache":     "cave",
    "🌍 Hebrew / RTL":        "oasis",
    "🎯 Long-Running":        "plain",
    "✨ Active":             "plain",
}

MAX_CLUSTERS = 4
MAX_PER_CLUSTER = 8


def _cluster_key(q: dict) -> str:
    tags = [t.lower() for t in (q.get("tags") or [])]
    name = (q.get("name") or "").lower()
    for keys, label in TAG_RULES:
        for t in tags:
            for k in keys:
                if t == k or t.startswith(k + "-") or k in t:
                    return label
    for keys, label in NAME_RULES:
        for k in keys:
            if k in name:
                return label
    return "✨ Active"


def cluster_quests(quests: list[dict]) -> tuple[list[tuple[str, list[dict]]], list[dict], list[dict]]:
    """Return ([(label, [quest, ...])], locked_list, done_list).
    Clusters capped to MAX_CLUSTERS, sorted by size desc.
    Done + locked = secondary buckets."""
    current = [q for q in quests if q.get("status") == "current"]
    locked = [q for q in quests if q.get("status") == "locked"]
    done = [q for q in quests if q.get("status") == "done"]

    clusters: dict[str, list[dict]] = {}
    for q in current:
        k = _cluster_key(q)
        clusters.setdefault(k, []).append(q)

    items = sorted(clusters.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    if len(items) > MAX_CLUSTERS:
        kept = items[: MAX_CLUSTERS - 1]
        spill = items[MAX_CLUSTERS - 1 :]
        merged = []
        for _, qs in spill:
            merged.extend(qs)
        kept.append(("✨ Other Active", merged))
        items = kept

    # Cap per-cluster
    items = [(label, qs[:MAX_PER_CLUSTER]) for label, qs in items]

    return items, locked, done


# ============================================================
# COLOR HELPERS
# ============================================================

def progress_color(progress: float, status: str) -> str:
    """Status + progress → fill color (consistent across both themes)."""
    if status == "done":
        return "#9bd0c8"
    if status == "locked":
        return "#d8d8e0"
    if not progress:
        return "#d8d8e0"
    if progress >= 0.85:
        return "#ff8a4a"   # nearly done = coral
    if progress >= 0.5:
        return "#ffd24a"   # in progress = gold
    return "#6ec3ff"      # early = blue


# ============================================================
# THEME SWITCHER BANNER (shared)
# ============================================================

def switcher_banner(project_id: str, active_theme: str) -> str:
    themes = [
        ("default", f"/{project_id}/route.html", "📍 Default", active_theme == "default"),
        ("solar", f"/{project_id}/route-solar.html", "🌌 Solar", active_theme == "solar"),
        ("worldmap", f"/{project_id}/route-worldmap.html", "🗺 Worldmap", active_theme == "worldmap"),
    ]
    tabs = ""
    for _, href, label, active in themes:
        if active:
            tabs += f'<a class="theme-tab active" href="{href}">{label}</a>'
        else:
            tabs += f'<a class="theme-tab" href="{href}">{label}</a>'
    return f"""
<div class="theme-switcher">
  <span class="theme-switcher-label">Theme:</span>
  {tabs}
  <span class="theme-switcher-spacer"></span>
  <a class="theme-switcher-back" href="/">← All projects</a>
</div>
<style>
.theme-switcher {{ display:flex; gap:6px; align-items:center; padding:10px 22px; background:#11111c; border-bottom:1px solid #2a2a3a; font-family:-apple-system,sans-serif; font-size:12px; color:#aaacc4; }}
.theme-switcher-label {{ font-weight:600; margin-right:4px; }}
.theme-switcher-spacer {{ flex:1; }}
.theme-tab {{ padding:5px 12px; border:1px solid #2a2a3e; border-radius:14px; color:#aaacc4; text-decoration:none; transition:all .15s; }}
.theme-tab:hover {{ color:#fff; border-color:#ffd24a; }}
.theme-tab.active {{ background:#ffd24a; color:#2a3a4a; border-color:#ffd24a; font-weight:700; }}
.theme-switcher-back {{ color:#6ec3ff; text-decoration:none; font-size:11px; }}
.theme-switcher-back:hover {{ color:#fff; }}
</style>
"""


# ============================================================
# COMMON CSS (shared between solar + worldmap)
# ============================================================

COMMON_HEAD = """<link href="https://fonts.googleapis.com/css2?family=Fredoka:wght@500;600;700&display=swap" rel="stylesheet">
<style>
:root {{ --ink:#2a3a4a; --cream:#fffdf2; --gold:#ffd24a; --gold-shadow:#c9a020; --pink-now:#ff6a8a; --teal:#9bd0c8; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:'Fredoka',system-ui,sans-serif; background:#1a1a28; color:#e8e8ee; }}
header.proj {{ padding:18px 22px 10px; background:#11111c; border-bottom:1px solid #2a2a3a; }}
header.proj h1 {{ margin:0 0 4px; font-size:20px; font-weight:700; }}
header.proj .subtitle {{ font-size:12px; color:#aaacc4; font-family:-apple-system,sans-serif; margin-bottom:6px; }}
header.proj .stats {{ display:flex; gap:14px; flex-wrap:wrap; font-size:11px; color:#aaacc4; font-family:-apple-system,sans-serif; }}
header.proj .stats b {{ color:#ffd24a; }}
header.proj .level-pill {{ background:#ffd24a; color:#2a3a4a; padding:3px 10px; border-radius:11px; font-family:'Fredoka',sans-serif; font-weight:700; font-size:11px; }}
header.proj .xp-bar {{ display:inline-block; vertical-align:middle; width:100px; height:9px; background:#2a2a3e; border:1.5px solid #ffd24a; border-radius:5px; overflow:hidden; margin:0 4px; }}
header.proj .xp-bar i {{ display:block; height:100%; background:linear-gradient(90deg,#ffd24a,#ff8a4a); }}
.stage {{ background:var(--cream); border-top:3px solid var(--ink); border-bottom:3px solid var(--ink); padding:20px; }}
.stage svg {{ display:block; width:100%; height:auto; max-height:900px; }}
.qm, .solar {{ cursor:pointer; }}
.qm:hover, .solar:hover {{ filter:drop-shadow(0 2px 5px rgba(0,0,0,0.25)); }}
.twinkle {{ animation:tw 1.6s ease-in-out infinite; transform-origin:center; transform-box:fill-box; }}
@keyframes tw {{ 0%,100% {{ transform:scale(1); }} 50% {{ transform:scale(1.12); }} }}
.bobby {{ animation:bob 1.4s ease-in-out infinite; transform-origin:bottom center; transform-box:fill-box; }}
@keyframes bob {{ 0%,100% {{ transform:translateY(0); }} 50% {{ transform:translateY(-3px); }} }}
.lbl-bg {{ fill:#fff; stroke:var(--ink); stroke-width:2; }}
.lbl-text {{ font-family:'Fredoka',sans-serif; font-weight:700; font-size:11px; fill:var(--ink); }}
.lbl-sub {{ font-family:'Fredoka',sans-serif; font-weight:500; font-size:9px; fill:#6a7a8a; }}
.modal-backdrop {{ position:fixed; inset:0; background:rgba(0,0,0,.75); backdrop-filter:blur(4px); display:none; align-items:center; justify-content:center; z-index:100; font-family:-apple-system,sans-serif; }}
.modal-backdrop.open {{ display:flex; }}
.modal {{ background:var(--cream); border:4px solid var(--ink); border-radius:16px; padding:24px; width:540px; max-width:90vw; color:var(--ink); box-shadow:0 16px 60px rgba(0,0,0,.6); }}
.modal h3 {{ margin:0 0 4px; font-size:18px; font-weight:700; font-family:'Fredoka',sans-serif; }}
.modal .qid {{ color:#c9a020; font-size:11px; margin-bottom:14px; font-weight:600; text-transform:uppercase; letter-spacing:1px; font-family:'Fredoka',sans-serif; }}
.modal .qmeta {{ color:#6a7a8a; font-size:13px; margin-bottom:5px; }}
.modal .qprog {{ height:12px; background:#f0e4cc; border:2px solid var(--ink); border-radius:8px; margin:14px 0; overflow:hidden; }}
.modal .qprog-fill {{ height:100%; background:linear-gradient(180deg,#ff8a4a,#ff5a20); }}
.modal-actions {{ display:flex; gap:8px; margin-top:20px; }}
.modal-actions a, .modal-actions button {{ flex:1; padding:10px 14px; background:var(--gold); border:2.5px solid var(--ink); border-radius:10px; color:var(--ink); font-size:13px; font-weight:700; cursor:pointer; text-decoration:none; text-align:center; font-family:'Fredoka',sans-serif; box-shadow:0 3px 0 var(--gold-shadow); text-transform:uppercase; letter-spacing:1px; }}
.modal-actions a:hover, .modal-actions button:hover {{ transform:translateY(1px); box-shadow:0 2px 0 var(--gold-shadow); }}
.modal-actions .secondary {{ background:#fff; }}
</style>"""

COMMON_MODAL = """
<div class="modal-backdrop" id="modal-backdrop">
  <div class="modal">
    <div class="m-name-row" style="display:flex;align-items:flex-start;gap:8px;margin-bottom:4px;">
      <h3 id="m-name" style="flex:1;margin:0;cursor:text;" title="Click to rename">Quest Name</h3>
      <button id="m-rename-btn" onclick="startRename()" title="Rename quest" style="background:transparent;border:1.5px solid #c9a020;color:#c9a020;border-radius:6px;padding:2px 8px;font-family:'Fredoka',sans-serif;font-size:11px;font-weight:700;cursor:pointer;height:24px;">✏ Rename</button>
    </div>
    <div id="m-rename-edit" style="display:none;margin-bottom:10px;">
      <input id="m-rename-input" type="text" maxlength="200" style="width:100%;padding:8px 10px;font-family:'Fredoka',sans-serif;font-size:14px;font-weight:700;border:2px solid #2a3a4a;border-radius:6px;background:#fff;color:#2a3a4a;box-sizing:border-box;"/>
      <div style="display:flex;gap:6px;margin-top:6px;">
        <button onclick="commitRename()" style="flex:1;padding:6px;background:#5e9a4a;color:#fff;border:2px solid #2a3a4a;border-radius:6px;font-family:'Fredoka',sans-serif;font-weight:700;font-size:12px;cursor:pointer;">Save</button>
        <button onclick="cancelRename()" style="flex:1;padding:6px;background:#fff;color:#2a3a4a;border:2px solid #2a3a4a;border-radius:6px;font-family:'Fredoka',sans-serif;font-weight:700;font-size:12px;cursor:pointer;">Cancel</button>
      </div>
      <div id="m-rename-err" style="margin-top:6px;color:#c44545;font-size:11px;display:none;"></div>
    </div>
    <div class="qid" id="m-id">id</div>
    <div class="qmeta" id="m-status">Status: …</div>
    <div class="qmeta" id="m-cluster" style="display:none;">Cluster: …</div>
    <div class="qmeta" id="m-tags" style="display:none;"></div>
    <div class="qprog"><div class="qprog-fill" id="m-progress" style="width:0%;"></div></div>
    <div class="qmeta" id="m-progress-text">0% complete</div>
    <div class="modal-actions">
      <a id="m-open" href="#" target="_blank">Open quest card →</a>
      <button class="secondary" onclick="closeModal()">Close</button>
    </div>
  </div>
</div>
<script>
let _currentQuest = null;
function openModal(data) {
  _currentQuest = data;
  document.getElementById('m-name').textContent = data.name || data.id;
  document.getElementById('m-id').textContent = 'id: ' + data.id;
  document.getElementById('m-status').textContent = 'Status: ' + (data.status || '—');
  const clEl = document.getElementById('m-cluster');
  if (data.cluster) { clEl.textContent = 'Cluster: ' + data.cluster; clEl.style.display='block'; } else clEl.style.display='none';
  const tagsEl = document.getElementById('m-tags');
  if (data.tags && data.tags.length) { tagsEl.textContent = 'Tags: ' + data.tags.join(', '); tagsEl.style.display='block'; } else tagsEl.style.display='none';
  const pct = Math.round((data.progress || 0) * 100);
  document.getElementById('m-progress').style.width = pct + '%';
  document.getElementById('m-progress-text').textContent = pct + '% complete';
  document.getElementById('m-open').href = window.location.pathname.replace(/route(-\\w+)?\\.html$/, 'plan-card.html') + '?q=' + encodeURIComponent(data.id);
  cancelRename();  // reset rename UI on every open
  // Hide rename for synthetic entries (long-term/BH/castle)
  const renameBtn = document.getElementById('m-rename-btn');
  renameBtn.style.display = (data.id && data.id !== 'long-term') ? '' : 'none';
  document.getElementById('modal-backdrop').classList.add('open');
}
function closeModal() { document.getElementById('modal-backdrop').classList.remove('open'); }
function startRename() {
  if (!_currentQuest) return;
  const inp = document.getElementById('m-rename-input');
  inp.value = _currentQuest.name || _currentQuest.id;
  document.getElementById('m-rename-edit').style.display = 'block';
  document.getElementById('m-rename-btn').style.display = 'none';
  document.getElementById('m-rename-err').style.display = 'none';
  inp.focus();
  inp.select();
}
function cancelRename() {
  document.getElementById('m-rename-edit').style.display = 'none';
  document.getElementById('m-rename-btn').style.display = (_currentQuest && _currentQuest.id !== 'long-term') ? '' : 'none';
  document.getElementById('m-rename-err').style.display = 'none';
}
async function commitRename() {
  if (!_currentQuest) return;
  const newName = document.getElementById('m-rename-input').value.trim();
  if (!newName) {
    const err = document.getElementById('m-rename-err');
    err.textContent = 'Name cannot be empty';
    err.style.display = 'block';
    return;
  }
  // Project comes from URL path: /<project>/route-<theme>.html
  const proj = (window.location.pathname.split('/')[1] || '').trim();
  if (!proj) {
    const err = document.getElementById('m-rename-err');
    err.textContent = 'Could not detect project from URL';
    err.style.display = 'block';
    return;
  }
  try {
    const resp = await fetch('/api/quest/rename', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({project: proj, id: _currentQuest.id, name: newName}),
    });
    const j = await resp.json();
    if (!resp.ok || !j.ok) throw new Error(j.error || j.msg || ('HTTP ' + resp.status));
    _currentQuest.name = newName;
    document.getElementById('m-name').textContent = newName;
    cancelRename();
    // Reload map so the rename shows in the SVG too
    setTimeout(() => window.location.reload(), 600);
  } catch (e) {
    const err = document.getElementById('m-rename-err');
    err.textContent = 'Rename failed: ' + e.message;
    err.style.display = 'block';
  }
}
document.getElementById('modal-backdrop').addEventListener('click', e => { if (e.target.id === 'modal-backdrop') closeModal(); });
document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && document.getElementById('m-rename-edit').style.display === 'block') commitRename();
  if (e.key === 'Escape') { cancelRename(); closeModal(); }
});
</script>
"""


# ============================================================
# HEADER (shared)
# ============================================================

def header_html(project_id: str, project: dict, counts: dict) -> str:
    name = _html.escape(project.get("name") or project_id)
    subtitle = _html.escape(project.get("subtitle") or "")
    level = project.get("level", 1)
    xp = project.get("xp") or {"current": 0, "max": 100}
    xp_pct = int(100 * (xp.get("current", 0) / max(xp.get("max", 100), 1)))
    return f"""<header class="proj">
  <h1>{name}</h1>
  <div class="subtitle">{subtitle}</div>
  <div class="stats">
    <span class="level-pill">Level {level}</span>
    <span>XP <b>{xp.get('current', 0)}/{xp.get('max', 100)}</b> <span class="xp-bar"><i style="width:{xp_pct}%"></i></span></span>
    <span><b>{counts['total']}</b> quests</span>
    <span><b style="color:#ff6a8a;">{counts['current']}</b> current</span>
    <span><b style="color:#ffd24a;">{counts['locked']}</b> locked</span>
    <span><b style="color:#9bd0c8;">{counts['done']}</b> done</span>
  </div>
</header>"""


def quest_data_attr(q: dict, cluster: str | None = None) -> str:
    payload = {
        "id": q.get("id"),
        "name": q.get("name") or q.get("id"),
        "status": q.get("status"),
        "progress": q.get("progress", 0),
        "tags": q.get("tags") or [],
    }
    if cluster:
        payload["cluster"] = cluster
    j = json.dumps(payload).replace('"', "&quot;")
    return j


def short_label(q: dict, max_chars: int = 18) -> str:
    name = q.get("name") or q.get("id")
    # If name has obvious prefix, drop it for the planet label
    n = name.strip()
    # Drop "Phase X — " prefix etc.
    for sep in (" — ", " - ", ": "):
        if sep in n and len(n.split(sep)[1]) > 4:
            n = n.split(sep, 1)[1]
            break
    if len(n) > max_chars:
        n = n[: max_chars - 1] + "…"
    pct = int((q.get("progress") or 0) * 100)
    if pct > 0 and q.get("status") == "current":
        return f"{n} {pct}%"
    return n


# ============================================================
# SOLAR THEME — cartoon solar systems
# ============================================================

# 4 cluster anchor positions (top-left, top-right, bottom-left, bottom-right)
SOLAR_POSITIONS = [
    (320, 220),   # 0
    (1000, 220),  # 1
    (320, 700),   # 2
    (1000, 700),  # 3
]

# Planet orbital slots relative to sun (x, y, r)
PLANET_SLOTS = [
    (75, -10, 13),    # right
    (-75, -10, 13),   # left
    (0, -78, 12),     # top
    (28, 70, 11),     # bottom-right
    (-30, 70, 11),    # bottom-left
    (52, -55, 10),    # top-right diag
    (-52, -55, 10),   # top-left diag
    (0, 80, 9),       # far bottom
]


def render_solar_cluster(cx: int, cy: int, label: str, members: list[dict]) -> str:
    """SVG group for one cluster (sun + planets)."""
    # Determine cluster avg progress for sun color
    if not members:
        return ""
    avg = sum((q.get("progress") or 0) for q in members) / len(members)
    has_active = any(q.get("status") == "current" for q in members)
    sun_color = "#ff6a8a" if has_active and avg < 0.5 else ("#ff8a4a" if avg >= 0.85 else "#ffd24a")

    parts = [f'<g transform="translate({cx},{cy})">']
    parts.append('<circle r="80" fill="none" stroke="#2a3a4a" stroke-width="1.8" stroke-dasharray="3 5" opacity="0.35"/>')
    parts.append('<circle r="58" fill="none" stroke="#2a3a4a" stroke-width="1.5" stroke-dasharray="3 6" opacity="0.25"/>')

    # Sun (cluster lead = highest progress current quest)
    sun_q = max(members, key=lambda q: (q.get("progress") or 0))
    sun_data = quest_data_attr(sun_q, cluster=label)
    parts.append(
        f'<g class="solar" onclick="openModal({sun_data})">'
        f'<circle r="32" fill="{sun_color}" stroke="#2a3a4a" stroke-width="4"/>'
        '<g stroke="#2a3a4a" stroke-width="3" stroke-linecap="round">'
        '<line x1="0" y1="-40" x2="0" y2="-46"/><line x1="0" y1="40" x2="0" y2="46"/>'
        '<line x1="-40" y1="0" x2="-46" y2="0"/><line x1="40" y1="0" x2="46" y2="0"/>'
        '<line x1="-28" y1="-28" x2="-33" y2="-33"/><line x1="28" y1="28" x2="33" y2="33"/>'
        '<line x1="-28" y1="28" x2="-33" y2="33"/><line x1="28" y1="-28" x2="33" y2="-33"/>'
        '</g>'
        '<circle cx="-10" cy="-5" r="3" fill="#2a3a4a"/><circle cx="10" cy="-5" r="3" fill="#2a3a4a"/>'
        '<path d="M -8 8 Q 0 13 8 8" fill="none" stroke="#2a3a4a" stroke-width="2.5" stroke-linecap="round"/>'
        '</g>'
    )

    # Planets (other members)
    planets = [q for q in members if q is not sun_q]
    for q, slot in zip(planets, PLANET_SLOTS):
        px, py, pr = slot
        color = progress_color(q.get("progress") or 0, q.get("status") or "current")
        qdata = quest_data_attr(q, cluster=label)
        lbl = _html.escape(short_label(q))
        text_y = py - pr - 4 if py < 0 else py + pr + 10
        parts.append(
            f'<g class="solar" onclick="openModal({qdata})">'
            f'<circle cx="{px}" cy="{py}" r="{pr}" fill="{color}" stroke="#2a3a4a" stroke-width="3"/>'
            f'<text x="{px}" y="{text_y}" font-size="9" font-weight="700" fill="#2a3a4a" text-anchor="middle" font-family="Fredoka">{lbl}</text>'
            '</g>'
        )

    # Cluster label
    safe_label = _html.escape(label)
    parts.append(
        f'<rect x="-110" y="100" width="220" height="28" rx="14" fill="{sun_color}" stroke="#2a3a4a" stroke-width="3"/>'
        f'<text y="118" text-anchor="middle" font-size="13" font-weight="700" fill="#2a3a4a" font-family="Fredoka">{safe_label} ({len(members)})</text>'
    )
    parts.append('</g>')
    return "".join(parts)


def render_solar(project_id: str, project: dict) -> str:
    quests = project.get("quests") or []
    clusters, locked, done = cluster_quests(quests)
    counts = {"total": len(quests), "current": sum(1 for q in quests if q.get("status") == "current"),
              "locked": len(locked), "done": len(done)}

    # BH at center
    bh_label = _html.escape(project.get("subtitle") or project.get("name") or "Long-term goal")
    bh_data = json.dumps({
        "id": "long-term", "name": project.get("subtitle") or project.get("name"),
        "status": "goal", "progress": 0.4,
        "tags": []
    }).replace('"', "&quot;")

    cluster_svgs = []
    for i, (label, members) in enumerate(clusters[:MAX_CLUSTERS]):
        cx, cy = SOLAR_POSITIONS[i]
        cluster_svgs.append(render_solar_cluster(cx, cy, label, members))

    # Connector lines from each cluster to BH
    connectors = "".join(
        f'<line x1="{cx}" y1="{cy}" x2="660" y2="460" stroke="#ffd24a" stroke-width="1.2" '
        f'fill="none" stroke-dasharray="3 5" opacity="0.35"/>'
        for cx, cy in SOLAR_POSITIONS[: len(clusters)]
    )

    # Done galaxy (top)
    done_stars = ""
    if done:
        n = min(len(done), 17)
        cols = max(n, 1)
        x_step = 360 // cols
        for i in range(n):
            x = -180 + i * x_step
            y = (i % 3 - 1) * 8
            done_stars += f'<circle cx="{x}" cy="{y}" r="6" fill="#9bd0c8" stroke="#2a3a4a" stroke-width="1.5"/>'

    # Locked backlog (bottom)
    locked_preview = ""
    if locked:
        top_locked = sorted(locked, key=lambda q: -(q.get("progress") or 0))[:6]
        for i, q in enumerate(top_locked):
            xpos = -340 + i * 115
            pct = int((q.get("progress") or 0) * 100)
            name = _html.escape(short_label(q, 14))
            qdata = quest_data_attr(q, cluster="🔒 Backlog")
            locked_preview += (
                f'<g class="solar" onclick="openModal({qdata})" transform="translate({xpos},0)">'
                f'<circle r="6" fill="#d8d8e0" stroke="#2a3a4a" stroke-width="1.5"/>'
                f'<text x="0" y="20" font-size="9" font-weight="500" fill="#2a3a4a" text-anchor="middle" font-family="Fredoka">{name}</text>'
                f'</g>'
            )

    locked_extra = max(0, len(locked) - 6)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_html.escape(project.get('name') or project_id)} — Solar Map</title>
{COMMON_HEAD.replace('{', '{{').replace('}', '}}').replace('{{{{', '{').replace('}}}}', '}')}
</head>
<body>
{switcher_banner(project_id, 'solar')}
{header_html(project_id, project, counts)}
<div class="stage">
<svg viewBox="0 0 1320 900" preserveAspectRatio="xMidYMid meet">
<circle cx="660" cy="460" r="280" fill="none" stroke="#2a3a4a" stroke-width="2" stroke-dasharray="5 8" opacity="0.18"/>
<circle cx="660" cy="460" r="400" fill="none" stroke="#2a3a4a" stroke-width="1.5" stroke-dasharray="5 10" opacity="0.12"/>
{connectors}
<g transform="translate(660,460)" class="solar" onclick="openModal({bh_data})">
<ellipse rx="160" ry="38" fill="#ffd24a" stroke="#2a3a4a" stroke-width="5" transform="rotate(15)"/>
<ellipse rx="130" ry="26" fill="#ff8a3a" stroke="#2a3a4a" stroke-width="4" transform="rotate(15)"/>
<ellipse rx="105" ry="18" fill="#ffd24a" stroke="#2a3a4a" stroke-width="3" transform="rotate(15)"/>
<circle r="56" fill="#2a3a4a" stroke="#2a3a4a" stroke-width="5"/>
<circle r="50" fill="#0a0a14"/>
<circle cx="-13" cy="-6" r="6" fill="#fff"/><circle cx="13" cy="-6" r="6" fill="#fff"/>
<circle cx="-13" cy="-6" r="3" fill="#000"/><circle cx="13" cy="-6" r="3" fill="#000"/>
<path d="M -8 12 Q 0 18 8 12" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round"/>
<rect x="-110" y="92" width="220" height="30" rx="15" fill="#2a3a4a" stroke="#ffd24a" stroke-width="3"/>
<text y="112" text-anchor="middle" font-size="13" font-weight="700" fill="#ffd24a" font-family="Fredoka">★ {bh_label}</text>
</g>
{''.join(cluster_svgs)}
<g transform="translate(660,90)">
<ellipse rx="200" ry="36" fill="#e8f0e8" stroke="#2a3a4a" stroke-width="3" stroke-dasharray="4 6" opacity="0.55"/>
<text y="-48" text-anchor="middle" font-size="13" font-weight="700" fill="#5e9a4a" font-family="Fredoka">★ DONE GALAXY · {len(done)} quests ✓</text>
{done_stars}
</g>
<g transform="translate(660,850)">
<rect x="-380" y="-26" width="760" height="48" rx="24" fill="#fffdf2" stroke="#2a3a4a" stroke-width="3" stroke-dasharray="5 6"/>
<text x="-360" y="-2" font-size="11" font-weight="700" fill="#2a3a4a" font-family="Fredoka">🔒 BACKLOG · {len(locked)} locked</text>
{locked_preview}
<text x="340" y="-2" font-size="11" font-weight="700" fill="#c9a020" font-family="Fredoka">+{locked_extra} more</text>
</g>
</svg>
</div>
{COMMON_MODAL}
</body></html>"""


# ============================================================
# WORLDMAP THEME — Pokemon multi-region
# ============================================================

WM_REGIONS = [
    {"name": "TL", "rect": (100, 60, 320, 180), "label_xy": (260, 50)},
    {"name": "TR", "rect": (900, 60, 380, 200), "label_xy": (1090, 50)},
    {"name": "BL", "rect": (100, 500, 320, 200), "label_xy": (260, 490)},
    {"name": "BR", "rect": (900, 500, 380, 200), "label_xy": (1090, 490)},
]

# Town slot positions inside each region (relative to region top-left)
WM_TOWN_SLOTS = [
    (160, 50),  (260, 110), (60, 110), (210, 150), (110, 150), (260, 50), (60, 50), (160, 110),
]


def render_wm_region(region_rect: tuple[int, int, int, int], label_xy: tuple[int, int],
                     label: str, members: list[dict], is_largest: bool) -> str:
    rx, ry, rw, rh = region_rect
    safe_label = _html.escape(label)
    parts = [
        f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" fill="url(#grass-dark)" '
        f'stroke="#2a3a4a" stroke-width="2.5" stroke-dasharray="8 6" rx="14" opacity="0.6"/>',
        f'<text x="{label_xy[0]}" y="{label_xy[1]}" text-anchor="middle" font-family="Fredoka" '
        f'font-weight="700" font-size="13" fill="#2a3a4a">{safe_label} ({len(members)})</text>',
    ]

    # City (main quest = highest progress) in slot 0; rest as towns
    sorted_members = sorted(members, key=lambda q: -(q.get("progress") or 0))
    for i, q in enumerate(sorted_members[: MAX_PER_CLUSTER]):
        if i >= len(WM_TOWN_SLOTS):
            break
        tx_off, ty_off = WM_TOWN_SLOTS[i]
        tx = rx + tx_off
        ty = ry + ty_off
        qdata = quest_data_attr(q, cluster=label)
        color = progress_color(q.get("progress") or 0, q.get("status") or "current")
        lbl = _html.escape(short_label(q, 14))
        status = q.get("status") or "current"
        if i == 0 and is_largest:
            # Big city (Pokemon center) + trainer
            parts.append(
                f'<g class="qm" transform="translate({tx},{ty})" onclick="openModal({qdata})">'
                f'<polygon points="0,-30 -24,-12 -24,14 24,14 24,-12" fill="#c44545" stroke="#2a3a4a" stroke-width="2.5"/>'
                f'<rect x="-16" y="-2" width="32" height="16" fill="#fffdf2" stroke="#2a3a4a" stroke-width="2"/>'
                f'<circle cx="0" cy="-14" r="5" fill="#fff" stroke="#2a3a4a" stroke-width="2"/>'
                f'<line x1="0" y1="-30" x2="0" y2="-40" stroke="#2a3a4a" stroke-width="2"/>'
                f'<circle cx="0" cy="-42" r="3" fill="#ffd24a" class="twinkle"/>'
                # Trainer bobby
                '<g class="bobby" transform="translate(-50,0)">'
                '<ellipse cx="0" cy="22" rx="10" ry="3" fill="rgba(0,0,0,0.3)"/>'
                '<circle cx="0" cy="-8" r="9" fill="#ffd9a8" stroke="#3a2010" stroke-width="2"/>'
                '<circle cx="-3" cy="-9" r="1.2" fill="#3a2010"/><circle cx="3" cy="-9" r="1.2" fill="#3a2010"/>'
                '<path d="M -10 -14 Q 0 -22 10 -14 L 10 -10 L -10 -10 Z" fill="#d63a3a" stroke="#3a2010" stroke-width="2"/>'
                '<rect x="-7" y="0" width="14" height="14" fill="#3a78d0" stroke="#1a3060" stroke-width="2"/>'
                '<rect x="-9" y="14" width="6" height="8" fill="#3a2010"/><rect x="3" y="14" width="6" height="8" fill="#3a2010"/>'
                '</g>'
                f'<rect class="lbl-bg" x="-66" y="22" width="132" height="22" rx="4" fill="#ffd24a"/>'
                f'<text class="lbl-text" x="0" y="36" text-anchor="middle">{lbl}</text>'
                f'</g>'
            )
        elif i == 0:
            # City (Pokemon center, no trainer)
            parts.append(
                f'<g class="qm" transform="translate({tx},{ty})" onclick="openModal({qdata})">'
                f'<polygon points="0,-28 -22,-12 -22,12 22,12 22,-12" fill="#c44545" stroke="#2a3a4a" stroke-width="2.5"/>'
                f'<rect x="-14" y="-2" width="28" height="14" fill="#fffdf2" stroke="#2a3a4a" stroke-width="1.5"/>'
                f'<circle cx="0" cy="-14" r="5" fill="#fff" stroke="#2a3a4a" stroke-width="1.5"/>'
                f'<circle cx="0" cy="-36" r="3" fill="#ffd24a" class="twinkle"/>'
                f'<line x1="0" y1="-28" x2="0" y2="-34" stroke="#2a3a4a" stroke-width="1.5"/>'
                f'<rect class="lbl-bg" x="-60" y="18" width="120" height="22" rx="4"/>'
                f'<text class="lbl-text" x="0" y="32" text-anchor="middle">{lbl}</text>'
                f'</g>'
            )
        else:
            # Town (small roof)
            gable_color = "#3a78d0" if (i % 3 == 0) else ("#d63a3a" if (i % 3 == 1) else "#5a8a3a")
            dashed = ' stroke-dasharray="3 2" opacity="0.85"' if status != "current" else ""
            parts.append(
                f'<g class="qm" transform="translate({tx},{ty})" onclick="openModal({qdata})">'
                f'<rect x="-14" y="-10" width="28" height="20" fill="#fff" stroke="#2a3a4a" stroke-width="2"{dashed}/>'
                f'<polygon points="-18,-10 0,-22 18,-10" fill="{gable_color}" stroke="#2a3a4a" stroke-width="2"/>'
                f'<rect class="lbl-bg" x="-42" y="14" width="84" height="20" rx="4"/>'
                f'<text class="lbl-text" x="0" y="27" text-anchor="middle">{lbl}</text>'
                f'</g>'
            )

    return "".join(parts)


def render_worldmap(project_id: str, project: dict) -> str:
    quests = project.get("quests") or []
    clusters, locked, done = cluster_quests(quests)
    counts = {"total": len(quests), "current": sum(1 for q in quests if q.get("status") == "current"),
              "locked": len(locked), "done": len(done)}

    # Find which cluster has the most-active quest (for trainer)
    max_progress = 0.0
    largest_cluster_idx = 0
    for i, (label, members) in enumerate(clusters):
        m = max(((q.get("progress") or 0) for q in members), default=0)
        if m > max_progress:
            max_progress = m
            largest_cluster_idx = i

    region_svgs = []
    for i, (label, members) in enumerate(clusters[:MAX_CLUSTERS]):
        region = WM_REGIONS[i]
        is_largest = (i == largest_cluster_idx and counts["current"] > 0)
        region_svgs.append(render_wm_region(region["rect"], region["label_xy"], label, members, is_largest))

    # Castle (center, long-term goal)
    castle_label = _html.escape(project.get("subtitle") or project.get("name") or "Long-term goal")
    castle_data = json.dumps({
        "id": "long-term", "name": project.get("subtitle") or project.get("name"),
        "status": "goal", "progress": 0.4, "tags": []
    }).replace('"', "&quot;")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_html.escape(project.get('name') or project_id)} — Worldmap</title>
{COMMON_HEAD.replace('{', '{{').replace('}', '}}').replace('{{{{', '{').replace('}}}}', '}')}
</head>
<body>
{switcher_banner(project_id, 'worldmap')}
{header_html(project_id, project, counts)}
<div class="stage">
<svg viewBox="0 0 1320 760" preserveAspectRatio="xMidYMid slice">
<defs>
<pattern id="grass-pat" patternUnits="userSpaceOnUse" width="14" height="14">
<rect width="14" height="14" fill="#8fc97a"/>
<path d="M 3 14 L 1 9 M 7 14 L 5 7 M 11 14 L 9 9" stroke="#5e9a4a" stroke-width="1" fill="none"/>
</pattern>
<pattern id="grass-dark" patternUnits="userSpaceOnUse" width="14" height="14">
<rect width="14" height="14" fill="#a8d890"/>
<path d="M 3 14 L 1 9 M 7 14 L 5 7 M 11 14 L 9 9" stroke="#3a6a2a" stroke-width="1" fill="none"/>
</pattern>
<pattern id="sand-pat" patternUnits="userSpaceOnUse" width="10" height="10">
<rect width="10" height="10" fill="#e8c878"/>
<circle cx="3" cy="3" r="0.5" fill="#c9a050"/><circle cx="7" cy="7" r="0.5" fill="#c9a050"/>
</pattern>
</defs>
<rect width="1320" height="760" fill="url(#grass-pat)"/>
<g>
<polygon points="600,80 660,30 720,80" fill="#8a7a6a" stroke="#5a4a3a" stroke-width="2.5"/>
<polygon points="650,80 720,20 790,80" fill="#a08a78" stroke="#5a4a3a" stroke-width="2.5"/>
<polygon points="690,80 760,40 830,80" fill="#8a7a6a" stroke="#5a4a3a" stroke-width="2.5"/>
<polygon points="720,20 736,42 704,42" fill="#fff"/>
</g>
<path d="M 220 400 Q 360 320 460 280 Q 580 240 660 280 Q 780 320 900 300 Q 1020 280 1120 360 Q 1180 420 1180 480"
stroke="#c9a050" stroke-width="46" fill="none" stroke-linecap="round" opacity="0.4"/>
<path d="M 220 400 Q 360 320 460 280 Q 580 240 660 280 Q 780 320 900 300 Q 1020 280 1120 360 Q 1180 420 1180 480"
stroke="url(#sand-pat)" stroke-width="38" fill="none" stroke-linecap="round"/>
{''.join(region_svgs)}
<g class="qm" transform="translate(660,380)" onclick="openModal({castle_data})">
<ellipse cx="0" cy="48" rx="80" ry="14" fill="#5e9a4a" stroke="#3a6a2a" stroke-width="2.5"/>
<polygon points="0,-48 -38,-22 -38,22 38,22 38,-22" fill="#7a5a9a" stroke="#2a3a4a" stroke-width="3"/>
<rect x="-30" y="-12" width="60" height="34" fill="#9a7aba" stroke="#2a3a4a" stroke-width="2"/>
<rect x="-8" y="-2" width="16" height="24" fill="#2a3a4a"/>
<polygon points="-38,-28 -38,-22 -28,-22" fill="#2a3a4a"/>
<polygon points="28,-22 38,-28 38,-22" fill="#2a3a4a"/>
<polygon points="-14,-28 -14,-22 -4,-22" fill="#2a3a4a"/>
<polygon points="4,-22 14,-28 14,-22" fill="#2a3a4a"/>
<rect x="-44" y="-20" width="12" height="42" fill="#7a5a9a" stroke="#2a3a4a" stroke-width="2"/>
<polygon points="-44,-20 -38,-32 -32,-20" fill="#d63a3a" stroke="#2a3a4a" stroke-width="2"/>
<rect x="32" y="-20" width="12" height="42" fill="#7a5a9a" stroke="#2a3a4a" stroke-width="2"/>
<polygon points="32,-20 38,-32 44,-20" fill="#d63a3a" stroke="#2a3a4a" stroke-width="2"/>
<line x1="0" y1="-48" x2="0" y2="-62" stroke="#2a3a4a" stroke-width="2"/>
<polygon points="0,-62 14,-58 0,-54" fill="#ffd24a" stroke="#2a3a4a" stroke-width="1.5" class="twinkle"/>
<polygon points="-14,-14 -10,-22 -6,-16 -2,-22 2,-16 6,-22 10,-16 14,-14" fill="#ffd24a" stroke="#5a4a20"/>
<rect class="lbl-bg" x="-110" y="56" width="220" height="28" rx="14" fill="#7a5a9a"/>
<text class="lbl-text" x="0" y="74" text-anchor="middle" fill="#fff" font-size="13">★ {castle_label}</text>
<text class="lbl-sub" x="0" y="86" text-anchor="middle" fill="#fff" opacity="0.9">LONG-TERM GOAL</text>
</g>
<g transform="translate(660,730)">
<rect x="-200" y="-22" width="400" height="44" rx="22" fill="#fffdf2" stroke="#5e9a4a" stroke-width="3" stroke-dasharray="5 5"/>
<text x="-184" y="3" font-size="11" font-weight="700" fill="#5e9a4a" font-family="Fredoka">🏆 HALL OF FAME · {len(done)} done</text>
<text x="50" y="3" font-size="11" font-weight="500" fill="#2a3a4a" font-family="Fredoka">+ {len(locked)} locked in backlog</text>
</g>
</svg>
</div>
{COMMON_MODAL}
</body></html>"""


# ============================================================
# SWITCHER INJECTION INTO EXISTING route.html
# ============================================================

INJECTED_MARKER = "<!-- alt-theme-switcher-injected -->"


def inject_switcher_into_default(project_id: str) -> bool:
    """Add the theme switcher banner to existing route.html if not already injected.
    Returns True if injection happened, False if skipped."""
    route_path = SITE / project_id / "route.html"
    if not route_path.exists():
        return False
    content = route_path.read_text(encoding="utf-8")
    if INJECTED_MARKER in content:
        return False  # already injected
    banner = INJECTED_MARKER + "\n" + switcher_banner(project_id, "default")
    # Inject right after <body...> tag
    import re
    new_content, n = re.subn(r"(<body[^>]*>)", r"\1\n" + banner.replace("\\", "\\\\"), content, count=1)
    if n == 0:
        return False
    route_path.write_text(new_content, encoding="utf-8")
    return True


# ============================================================
# MAIN
# ============================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="Specific project id (default: all)")
    ap.add_argument("--theme", choices=["solar", "worldmap", "all"], default="all")
    ap.add_argument("--post-inject", action="store_true",
                    help="Also inject switcher banner into existing route.html for each project")
    args = ap.parse_args()

    if not DATA.exists():
        print(f"ERROR: data file not found at {DATA}", file=sys.stderr)
        return 1

    data = json.loads(DATA.read_text(encoding="utf-8"))
    projects = data.get("projects", {})

    if args.project:
        if args.project not in projects:
            print(f"ERROR: project '{args.project}' not in data. Known: {list(projects.keys())}", file=sys.stderr)
            return 1
        target_projects = {args.project: projects[args.project]}
    else:
        target_projects = projects

    n_written = 0
    n_injected = 0
    for pid, proj in target_projects.items():
        site_dir = SITE / pid
        site_dir.mkdir(parents=True, exist_ok=True)

        if args.theme in ("solar", "all"):
            out = site_dir / "route-solar.html"
            out.write_text(render_solar(pid, proj), encoding="utf-8")
            print(f"  wrote {out.relative_to(ROOT)}")
            n_written += 1

        if args.theme in ("worldmap", "all"):
            out = site_dir / "route-worldmap.html"
            out.write_text(render_worldmap(pid, proj), encoding="utf-8")
            print(f"  wrote {out.relative_to(ROOT)}")
            n_written += 1

        if args.post_inject:
            if inject_switcher_into_default(pid):
                print(f"  injected switcher into {pid}/route.html")
                n_injected += 1

    print(f"\ndone: {n_written} files written, {n_injected} switchers injected into existing route.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
