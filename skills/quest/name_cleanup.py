#!/usr/bin/env python3
"""Quest Name Cleanup — detect bad codename quest NAMES, propose short thematic
names, preview before/after as HTML, and apply (name-only).

PHILOSOPHY (operator-set, 2026-06-02 — OGAS):
  - `name` = SHORT thematic label (<= ~5 words), human-readable. The card title.
  - goal/mission lives in `desc` — the dashboard already renders it as the card subtitle.
  - NEVER cram the goal/mission into the name (no long sentences as names).
  - NEVER change the `id` — it anchors plan-card URLs, session claims, and depends_on.
  - Detection + HTML preview + apply are automatic; the short NAME itself is human
    (operator/Claude) judgment — auto-suggestions are a STARTING POINT, edit them.
  - A name is "bad" when it's a machine artifact: a bare `Entry NNN <titlecased slug>`
    stub, or a whimsical plan-mode codename whose slug == the id (e.g. "Fizzy Dove").
    Names that already read as a goal/theme are LEFT ALONE.

WORKFLOW (the routine):
  1. scan   -> detect flagged quests + best-effort short-name suggestions -> proposals JSON + table
  2. (edit the proposals JSON — make each name short + thematic, your style)
  3. html   -> before/after preview served on a local port; operator EYEBALLS (visual-first gate)
  4. apply  -> name-only updates via quest.py (id + desc untouched); re-renders the dashboard

Usage:
  name_cleanup.py scan  --project ogas [--out PROPOSALS.json]
  name_cleanup.py html  --project ogas [--in PROPOSALS.json] [--port 8788]
  name_cleanup.py apply --project ogas --in PROPOSALS.json
"""
import argparse, json, re, subprocess, sys, pathlib, html as _html

HOME = pathlib.Path.home()
QUESTS = HOME / ".claude/quest/data/quests.json"
QUEST_PY = HOME / ".claude/skills/quest/quest.py"
PLANS = HOME / ".claude/plans"
DEFAULT_OUT = HOME / ".claude/quest/run/name-cleanup-proposals.json"
PREVIEW_DIR = pathlib.Path("/tmp/claude/quest-name-cleanup")

SRC_COLOR = {"reformat": "#0369a1", "H1": "#15803d", "desc": "#a16207", "ASK": "#b91c1c"}


def _slug(s): return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
def _clean(s): return re.sub(r"\s+", " ", (s or "")).strip()


def _first_clause(s, n=90):
    s = _clean(s)
    s = re.split(r"(?<=[.!?])\s", s, 1)[0]
    return s[:n].rsplit(" ", 1)[0] + "…" if len(s) > n else s


def _already_good(name):
    """A name that already reads as a goal/theme: has a separator + real length."""
    return bool(re.search(r"[—:]|#\d", name)) and len(name) > 25


def _is_codename(name, qid):
    if _already_good(name):
        return False
    alpha = bool(re.fullmatch(r"[A-Za-z ]+", name))
    sn = _slug(name)
    # bare "Entry 463 Tier1 Inline Editor ..." machine stub (no #/—/:)
    if re.match(r"^entry \d+ ", name.lower()) and not re.search(r"[#—:]", name):
        return True
    # whimsical plan-mode codename: pure alpha AND slugifies to (a prefix of) the id
    if alpha and (sn == qid or (sn in qid and len(sn) < len(qid))):
        return True
    return False


def _plan_h1(planpath):
    if not planpath:
        return None
    p = pathlib.Path(planpath)
    p = p if p.is_absolute() else PLANS / p.name
    if not p.exists():
        return None
    for ln in p.read_text(errors="ignore").splitlines():
        m = re.match(r"^#\s+(.*)", ln.strip())
        if m:
            return re.sub(r"^Plan:\s*", "", m.group(1).strip())[:80]
    return None


def _suggest(q, shared_plan):
    """Best-effort SHORT name suggestion (a starting point — edit by hand)."""
    name, qid, desc = q.get("name", "") or "", q.get("id", ""), _clean(q.get("desc", ""))
    plan = (q.get("plan") or "").strip()
    # Entry stub -> drop the prefix, take a short thematic slice of the title words
    m = re.match(r"^Entry \d+\s+(.*)", name)
    if m:
        words = m.group(1).split()
        return " ".join(words[:5]), "reformat"
    if plan and not shared_plan and (h1 := _plan_h1(plan)) and _slug(h1) != qid:
        return " ".join(h1.split()[:6]), "H1"
    if desc:
        return " ".join(_first_clause(desc).split()[:5]), "desc"
    return "(EDIT ME — no source)", "ASK"


def _load():
    return json.loads(QUESTS.read_text())


def _project_quests(proj):
    d = _load()
    if proj not in d.get("projects", {}):
        sys.exit(f"unknown project '{proj}'. known: {list(d['projects'])}")
    return d["projects"][proj]["quests"]


def cmd_scan(a):
    qs = _project_quests(a.project)
    from collections import Counter
    plan_count = Counter(pathlib.Path((q.get("plan") or "").strip()).name
                         for q in qs if (q.get("plan") or "").strip())
    flagged, good = [], 0
    for q in qs:
        name, qid = q.get("name", "") or "", q.get("id", "")
        if _already_good(name):
            good += 1
            continue
        if _is_codename(name, qid):
            shared = plan_count[pathlib.Path((q.get("plan") or "").strip()).name] > 1 if (q.get("plan") or "").strip() else False
            sug, src = _suggest(q, shared)
            flagged.append({"id": qid, "n": q.get("n"), "status": q.get("status"),
                            "before": name, "suggested": sug, "source": src,
                            "goal": _first_clause(q.get("desc", "") or "")})
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"project": a.project, "renames": flagged}, indent=2, ensure_ascii=False))
    print(f"SCAN {a.project}: {len(flagged)} flagged · {good} already-good · {len(qs)} total")
    print(f"proposals -> {out}  (edit 'suggested' to short thematic names, then run html/apply)\n")
    for r in flagged:
        print(f"#{r['n']} [{r['source']}] {r['before']}\n   ->> {r['suggested']}")
    return 0


def cmd_html(a):
    src = pathlib.Path(a.infile or DEFAULT_OUT)
    data = json.loads(src.read_text())
    qs = {q["id"]: q for q in _project_quests(data["project"])}
    cards = ""
    for r in data["renames"]:
        q = qs.get(r["id"], {})
        goal = _first_clause(q.get("desc", "") or r.get("goal", "") or "(add a 1-line goal in desc)", 120)
        c = SRC_COLOR.get(r.get("source", ""), "#475569")
        cards += f'''<div class="card"><div class="cn">#{_html.escape(str(r.get("n","?")))}</div>
<div class="col"><div class="lbl">before</div><div class="bad">{_html.escape(r["before"])}</div></div>
<div class="ar">&rarr;</div>
<div class="col"><div class="lbl">after &mdash; card render</div>
<div class="title">{_html.escape(r["suggested"])}</div><div class="sub">{_html.escape(goal)}</div></div></div>'''
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Quest Name Cleanup &mdash; {_html.escape(data["project"])}</title>
<style>:root{{--ink:#0f172a;--sub:#475569;--line:#e2e8f0;--bg:#f8fafc;--p:#2563eb}}*{{box-sizing:border-box}}
body{{margin:0;font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--ink)}}
.wrap{{max-width:1100px;margin:0 auto;padding:32px 24px 80px}}h1{{font-size:22px;margin:0 0 6px;letter-spacing:-.02em}}
.lead{{color:var(--sub);font-size:14px;margin:0 0 18px}}
.banner{{background:#eff6ff;border:1px solid #bfdbfe;color:#1e3a8a;border-radius:12px;padding:12px 16px;font-size:13px;margin-bottom:24px}}
.card{{display:grid;grid-template-columns:48px 1fr 28px 1.4fr;gap:14px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:12px}}
.cn{{font-weight:700;color:#94a3b8}}.lbl{{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#94a3b8;margin-bottom:3px}}
.bad{{color:#b91c1c;background:#fef2f2;border-radius:6px;padding:4px 8px;font-size:13px;text-decoration:line-through;text-decoration-color:#fca5a5;display:inline-block}}
.ar{{color:var(--p);font-weight:700;text-align:center;font-size:18px}}.title{{font-size:16px;font-weight:700;letter-spacing:-.01em}}
.sub{{font-size:12.5px;color:var(--sub);margin-top:3px;line-height:1.45}}.col{{min-width:0}}
@media(max-width:640px){{.card{{grid-template-columns:1fr;gap:8px}}.ar{{display:none}}}}</style></head>
<body><div class="wrap"><h1>Quest Name Cleanup &mdash; {_html.escape(data["project"])}</h1>
<p class="lead">{len(data["renames"])} renames &middot; DRY RUN &mdash; nothing written until <code>apply</code></p>
<div class="banner"><b>Model:</b> the big line is the <b>name</b> (short, thematic). The grey line is the <b>goal</b> (lives in <code>desc</code>, rendered as the card subtitle). The <code>id</code> never changes.</div>
{cards}</div></body></html>'''
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    (PREVIEW_DIR / "index.html").write_text(page)
    print(f"preview -> {PREVIEW_DIR/'index.html'}")
    print(f"serve:  setsid python3 -m http.server {a.port} --directory {PREVIEW_DIR} >/dev/null 2>&1 &")
    print(f"open:   http://localhost:{a.port}/")
    return 0


def cmd_apply(a):
    src = pathlib.Path(a.infile or DEFAULT_OUT)
    data = json.loads(src.read_text())
    proj = data["project"]
    ok = fail = 0
    for r in data["renames"]:
        new = r["suggested"]
        if not new or new.startswith("(EDIT") or new.startswith("(ASK"):
            print(f"  SKIP (unedited): #{r.get('n')} {r['id']}")
            continue
        res = subprocess.run([sys.executable, str(QUEST_PY), "update", proj, r["id"], "--name", new],
                             capture_output=True, text=True)
        if res.returncode == 0:
            ok += 1; print(f"  set #{r.get('n')}: {new}")
        else:
            fail += 1; print(f"  FAIL #{r.get('n')} {r['id']}: {res.stderr.strip()[:120]}")
    print(f"\nAPPLY {proj}: {ok} renamed, {fail} failed. (names only; ids + descs untouched)")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser(description="Quest name cleanup — short thematic names, goal stays in desc")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("--project", required=True); s.add_argument("--out", default=str(DEFAULT_OUT)); s.set_defaults(fn=cmd_scan)
    h = sub.add_parser("html"); h.add_argument("--project", required=True); h.add_argument("--in", dest="infile", default=None); h.add_argument("--port", type=int, default=8788); h.set_defaults(fn=cmd_html)
    ap2 = sub.add_parser("apply"); ap2.add_argument("--project", required=True); ap2.add_argument("--in", dest="infile", default=None); ap2.set_defaults(fn=cmd_apply)
    a = ap.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
