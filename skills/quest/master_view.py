#!/usr/bin/env python3
"""Master-view renderer for the quest dashboard (additive, reversible).

INJECTS a board of MASTER quest cards into the project's real `quest-log.html`
— it does NOT replace the page. The entire original quest-log (header, XP bar,
Active/Visited/Sealed filters, Show-All/Active-Only/All, search, the flat
135-card grid, and all its JS) is kept verbatim. We add:
  - a thin `Master quests | All quests` switch above the grids,
  - the master-card grid (default-visible) with one card per `project["epics"]`,
  - a click-popup per master listing its sub-quests (clickable → plan-card),
  - CSS so the master grid shows by default and the flat grid shows when the
    user picks "All quests" OR touches any real filter/search control.

So the QUEST LOG opens to the 7 master plans (with full chrome), and any
filter/search interaction drops into the familiar flat list. Nothing removed.

Reversible: render.py only calls this when project.master_view_enabled is truthy
AND ~/.claude/quest/master-view-disabled is absent. When off, quest-log.html
stays the plain flat page. The flat grid + all original markup live INSIDE the
injected page too, so nothing is ever lost.

Master illus uses the theme's real landmark drawings (epic["landmark"]).
Tagline = epic["tagline"]. Worldmap-tuned; other themes opt in later via `epics`.
"""
import pathlib, html as H

_HERE = pathlib.Path(__file__).resolve().parent


def _esc(s): return H.escape(str(s or ""))


def _chev():
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>')


def _xicon():
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>')


_EXTRA = '''<style>
 /* --- master-view injection (additive) --- */
 .mvbar{display:flex;gap:8px;padding:14px 24px 0;align-items:center}
 .mvbar .mvbtn{padding:7px 16px;background:#fffdf2;border:2.5px solid #2a3a4a;border-radius:14px;font-weight:700;font-size:13px;color:#2a3a4a;letter-spacing:.5px;cursor:pointer;font-family:inherit}
 .mvbar .mv-on{background:#2a3a4a;color:#ffd24a}
 body.qd-flat .mvbar .mv-on{background:#fffdf2;color:#2a3a4a}
 body.qd-flat .mvbar .mv-all{background:#2a3a4a;color:#ffd24a}
 .master-grid{padding:22px 24px;display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:20px;background:#fffdf2}
 body.qd-flat .master-grid{display:none}
 body:not(.qd-flat) .grid{display:none !important}
 /* master card — own class so the flat-card JS never touches it */
 .mcard{display:block;background:#fffdf2;border:4px solid #5a1818;border-radius:14px;overflow:hidden;box-shadow:0 5px 0 #5a1818;cursor:pointer;position:relative;transition:transform .15s;text-decoration:none}
 .mcard:hover{transform:translateY(-2px)}
 .mcard .illus{height:120px}
 .mcard .illus svg{width:100%;height:100%;display:block}
 .mcard .num-badge{position:absolute;top:8px;left:8px}
 .stat-pill.master{position:absolute;top:8px;right:8px;background:#ffd24a;color:#6a4828;border:2px solid #c9a020;border-radius:6px;font-weight:700;font-size:10px;letter-spacing:2px;padding:3px 8px;box-shadow:0 2px 0 #c9a020}
 .mcard .body{padding:14px 16px}
 .mcard .qname{font-size:18px;font-weight:700;color:#2a3a4a;margin:0;line-height:1.15}
 .mtagline{font-size:12.5px;color:#6a7a8a;font-weight:500;line-height:1.35;margin:5px 0 2px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
 .mprog{margin-top:9px}
 .mprog-row{display:flex;justify-content:space-between;font-size:11px;font-weight:700;color:#5a1818;letter-spacing:.5px;margin-bottom:4px}
 .mprog-bar{height:11px;background:#f0e4cc;border:2px solid #2a3a4a;border-radius:7px;overflow:hidden}
 .mprog-fill{display:block;height:100%;background:linear-gradient(180deg,#ff8a5a,#e0501a)}
 .mprog-cnt{margin-top:7px;font-size:12px;color:#6a7a8a;font-weight:600}
 .clickhint{display:flex;align-items:center;justify-content:center;gap:5px;font-size:11px;color:#9aaab8;padding:9px 0 2px;font-weight:600;letter-spacing:.5px;border-top:1.5px dashed #e0d4bc;margin-top:11px}.clickhint svg{width:13px;height:13px}
 /* popup */
 .qbackdrop{position:fixed;inset:0;background:rgba(20,40,60,.55);display:none;align-items:flex-start;justify-content:center;padding:40px 16px;z-index:9999;overflow:auto}.qbackdrop.show{display:flex}
 .qmodal{display:none;width:100%;max-width:700px;background:#fffdf2;border:4px solid #2a3a4a;border-radius:16px;box-shadow:0 16px 40px rgba(0,0,0,.4);overflow:hidden}.qmodal.show{display:block}
 .qm-head{padding:16px 20px;background:linear-gradient(180deg,#fff,#f7eed8);border-bottom:4px solid #2a3a4a;display:flex;align-items:center;gap:14px}
 .qm-ic{width:64px;height:48px;flex:none;background:linear-gradient(180deg,#cfeaf7 0%,#cfeaf7 40%,#9ed18a 40%);border:3px solid #2a3a4a;border-radius:10px;overflow:hidden}.qm-ic svg{width:100%;height:100%;display:block}
 .qm-tt{flex:1;min-width:0}.qm-name{font-size:20px;font-weight:700;color:#2a3a4a;line-height:1.1}.qm-sub{font-size:12.5px;color:#6a7a8a;font-weight:500;margin-top:2px}
 .qm-roll{display:flex;align-items:center;gap:10px;margin-top:7px}
 .qm-bar{flex:1;max-width:240px;height:13px;background:#f0e4cc;border:2.5px solid #2a3a4a;border-radius:9px;overflow:hidden}.qm-fill{display:block;height:100%;background:linear-gradient(180deg,#ff8a5a,#e0501a)}
 .qm-pct{font-weight:700;font-size:17px;color:#5a1818}.qm-cnt{font-size:12px;color:#6a7a8a;font-weight:600}
 .qm-x{flex:none;width:36px;height:36px;border-radius:50%;background:#e0d4bc;border:2.5px solid #2a3a4a;color:#2a3a4a;cursor:pointer;display:flex;align-items:center;justify-content:center}.qm-x svg{width:16px;height:16px}.qm-x:hover{background:#ffd24a}
 .qm-body{padding:8px 16px 16px;max-height:62vh;overflow:auto}
 .sq{display:flex;align-items:center;gap:12px;padding:12px 10px;border-bottom:1.5px dashed #d8c8a0;text-decoration:none;border-radius:8px;transition:background .1s}
 .sq:last-child{border-bottom:none}.sq:hover{background:#f7eed8}
 .sq-num{flex:none;min-width:34px;height:27px;padding:0 7px;display:flex;align-items:center;justify-content:center;border-radius:8px;font-weight:700;font-size:12px;border:2px solid #5a1818;box-shadow:0 2px 0 #5a1818;background:#ff6a3a;color:#fff}
 .sq.z .sq-num{background:#e0d4bc;color:#6a4828;border-color:#c9a020;box-shadow:0 2px 0 #c9a020}
 .sq.done .sq-num{background:#5e9a4a;color:#fff;border-color:#2e6a2a;box-shadow:0 2px 0 #2e6a2a}
 .sq-main{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px}
 .sq-name{font-weight:700;font-size:14px;color:#2a3a4a;line-height:1.25;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
 .sq-next{font-size:11.5px;color:#6a7a8a;font-weight:500;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
 .sq-bar{flex:none;width:92px;height:9px;background:#f0e4cc;border:2px solid #2a3a4a;border-radius:6px;overflow:hidden}.sq-fill{display:block;height:100%;background:linear-gradient(180deg,#ff8a5a,#e0501a)}
 .sq-pct{flex:none;width:36px;text-align:right;font-weight:700;font-size:12px;color:#5a1818}
 .sq-go{flex:none;color:#9aaab8}.sq-go svg{width:16px;height:16px}.sq:hover .sq-go{color:#5a1818}
</style>'''

_JS = '''<script>
(function(){
  var b=document.body;
  function flat(on){b.classList.toggle('qd-flat',!!on);}
  document.querySelectorAll('.mv-all').forEach(function(x){x.addEventListener('click',function(){flat(true);});});
  document.querySelectorAll('.mv-on').forEach(function(x){x.addEventListener('click',function(){flat(false);window.scrollTo(0,0);});});
  // Any real status/show-all/active/all filter click reveals the flat list.
  document.querySelectorAll('.filters .filt').forEach(function(x){x.addEventListener('click',function(){flat(true);});});
  var s=document.querySelector('.qd-search input'); if(s){s.addEventListener('input',function(){if(s.value)flat(true);});}
  window.openM=function(id){var m=document.getElementById(id);if(m){m.classList.add('show');document.getElementById('qd-bk').classList.add('show');b.style.overflow='hidden';}};
  window.closeM=function(){document.querySelectorAll('.qmodal.show').forEach(function(m){m.classList.remove('show');});var bk=document.getElementById('qd-bk');if(bk)bk.classList.remove('show');b.style.overflow='';};
  document.addEventListener('click',function(e){if(e.target&&e.target.id==='qd-bk')closeM();});
  document.addEventListener('keydown',function(e){if(e.key==='Escape')closeM();});
  // Deep-link from the route map: quest-log.html#epic-<id> auto-opens that master popup.
  var _h=location.hash||'';if(_h.indexOf('#epic-')===0){var _m=document.querySelector('.qmodal[data-epic="'+_h.slice(6)+'"]');if(_m){openM(_m.id);}}
})();
</script>'''


def _load_landmarks(theme):
    d = _HERE / "themes" / theme / "landmarks"
    if not d.exists():
        return {}
    return {f.name.replace(".svg.tmpl", ""): f.read_text(encoding="utf-8").strip()
            for f in d.glob("*.svg.tmpl")}


def _illus(land_svg, ty=108):
    return (f'<svg viewBox="0 0 280 150" preserveAspectRatio="xMidYMid meet">'
            f'<path d="M 0 90 Q 80 80 140 90 Q 200 100 280 88 L 280 150 L 0 150 Z" fill="#5cba5a"/>'
            f'<ellipse cx="140" cy="135" rx="56" ry="6" fill="rgba(0,0,0,0.18)"/>'
            f'<g transform="translate(140,{ty})">{land_svg}</g></svg>')


def render_master_log(pid, project, site_dir):
    """Inject the master board into <site_dir>/quest-log.html (in place) and
    write an alias master-log.html. Returns the path or None if skipped."""
    site_dir = pathlib.Path(site_dir)
    qlog = site_dir / "quest-log.html"
    if not qlog.exists():
        return None
    t = qlog.read_text(encoding="utf-8")
    gi = t.find('<div class="grid">')
    hc = t.rfind("</head>")
    bc = t.rfind("</body>")
    if gi < 0 or hc < 0 or bc < 0:
        return None  # unexpected shape — leave the flat page untouched

    theme = project.get("theme", "worldmap")
    LAND = _load_landmarks(theme)
    quests = project.get("quests", [])
    epics = project.get("epics", [])
    by_epic = {}
    for q in quests:
        e = q.get("epic")
        if e:
            by_epic.setdefault(e, []).append(q)

    cards, modals = [], []
    for i, ep in enumerate(epics):
        eid = ep.get("id", f"epic{i}")
        members = sorted(by_epic.get(eid, []), key=lambda x: -x.get("progress", 0))
        if not members:
            continue
        roll = sum(m.get("progress", 0) for m in members) / len(members)
        n = len(members)
        fl = sum(1 for m in members if 0 < m.get("progress", 0) < 1)
        land = LAND.get(ep.get("landmark", "house"), "")
        mid = f"qm{i}"
        name = ep.get("name", eid)
        tag = ep.get("tagline", "")
        cards.append(
            f'<a class="mcard" onclick="openM(\'{mid}\');return false;" href="#">'
            f'<div class="illus">{_illus(land)}</div>'
            f'<div class="num-badge">{n}</div><span class="stat-pill master">MASTER</span>'
            f'<div class="body"><h3 class="qname">{_esc(name)}</h3>'
            f'<div class="mtagline">{_esc(tag)}</div>'
            f'<div class="mprog"><div class="mprog-row"><span>PROGRESS</span><span>{int(roll*100)}%</span></div>'
            f'<div class="mprog-bar"><div class="mprog-fill" style="width:{int(roll*100)}%"></div></div></div>'
            f'<div class="mprog-cnt">{n} sub-quests · {fl} in flight</div>'
            f'<div class="clickhint">{_chev()} click to open</div></div></a>'
        )
        badge = _illus(land, ty=112)
        rows = []
        for m in members:
            p = m.get("progress", 0)
            cls = "done" if m.get("status") == "done" else ("" if p > 0 else "z")
            nx = _esc((m.get("next_step") or "").strip()[:140])
            nxt = f'<span class="sq-next">▶ {nx}</span>' if nx else ""
            rows.append(
                f'<a class="sq {cls}" href="plan-card.html?q={_esc(m.get("id"))}" target="_blank">'
                f'<span class="sq-num">#{_esc(m.get("n"))}</span>'
                f'<span class="sq-main"><span class="sq-name">{_esc(m.get("name",""))}</span>{nxt}</span>'
                f'<span class="sq-bar"><span class="sq-fill" style="width:{int(p*100)}%"></span></span>'
                f'<span class="sq-pct">{int(p*100)}%</span><span class="sq-go">{_chev()}</span></a>'
            )
        modals.append(
            f'<div class="qmodal" id="{mid}" data-epic="{_esc(eid)}"><div class="qm-head"><span class="qm-ic">{badge}</span>'
            f'<div class="qm-tt"><div class="qm-name">{_esc(name)}</div><div class="qm-sub">{_esc(tag)}</div>'
            f'<div class="qm-roll"><span class="qm-bar"><span class="qm-fill" style="width:{int(roll*100)}%"></span></span>'
            f'<span class="qm-pct">{int(roll*100)}%</span><span class="qm-cnt">{n} sub · {fl} in flight</span></div></div>'
            f'<button class="qm-x" onclick="closeM()" aria-label="Close">{_xicon()}</button></div>'
            f'<div class="qm-body">{"".join(rows)}</div></div>'
        )

    mvbar = ('<div class="mvbar"><button type="button" class="mvbtn mv-on">Master quests</button>'
             '<button type="button" class="mvbtn mv-all">All quests</button></div>')
    inject_top = mvbar + f'<div class="master-grid">{"".join(cards)}</div>'
    popup = f'<div class="qbackdrop" id="qd-bk">{"".join(modals)}</div>'

    combined = (
        t[:hc] + _EXTRA + t[hc:gi] + inject_top + t[gi:bc] + popup + _JS + t[bc:]
    )
    qlog.write_text(combined, encoding="utf-8")
    (site_dir / "master-log.html").write_text(combined, encoding="utf-8")  # alias
    return str(qlog)
