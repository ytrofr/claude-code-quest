#!/usr/bin/env python3
"""Quest Dashboard HTTP server.

Drops in for `python3 -m http.server`. Serves static HTML from
~/.claude/quest/site/, and adds a tiny JSON API for tag mutations the
dashboard UI uses to let the operator add/remove tags from a quest card
without dropping to the CLI.

Endpoints
---------
GET  /<path>              -> static file (same as SimpleHTTPRequestHandler)
POST /api/tags/add        -> body {project, id, tag}      -> add tag to quest
POST /api/tags/remove     -> body {project, id, tag}      -> remove tag
POST /api/tags/bind       -> body {project, id, name?}    -> add session:<key>
POST /api/tags/unbind     -> body {project, id}           -> remove this session's tag
GET  /api/session         ->                              -> {session_key, session_label}

Design
------
* Stdlib only (no fastapi/flask). Same `python3` runtime systemd uses.
* Binds to 127.0.0.1 like the previous server — never exposed to LAN.
* Tag mutations write quests.json atomically (write tmp + rename) and
  trigger a re-render via render.render_all().
* Render is in-process (not subprocess) for speed; on failure the API
  still returns 200 because the data write succeeded — UI shows the
  refresh, the next render fixes the visual.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Import sibling modules — this script lives in ~/.claude/skills/quest/
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import render as _render  # noqa: E402
import quest as _quest    # noqa: E402

SITE_DIR = Path.home() / ".claude" / "quest" / "site"
DATA_PATH = Path.home() / ".claude" / "quest" / "data" / "quests.json"

# Single writer lock — tag mutations must not interleave.
_WRITE_LOCK = threading.Lock()

# Tag character whitelist: letters, digits, dash, underscore, dot, colon, slash.
# Colon allows `session:limor:s2`, dot allows `v1.2`, slash for `area/auth`.
_TAG_RE = re.compile(r"^[A-Za-z0-9_:./\-]{1,64}$")


def _normalize_tag(raw: str) -> str:
    """Trim, lowercase the leading letter run, validate. Returns "" if invalid."""
    t = (raw or "").strip()
    if not t:
        return ""
    # Preserve the user's casing — tags are case-sensitive for display, but
    # we still validate against the whitelist.
    if not _TAG_RE.match(t):
        return ""
    return t


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: tmp file then rename in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _find_quest(data: dict, project_id: str, quest_id: str) -> dict | None:
    proj = (data.get("projects") or {}).get(project_id)
    if not proj:
        return None
    for q in proj.get("quests", []) or []:
        if q.get("id") == quest_id:
            return q
    return None


def _session_label() -> tuple[str | None, str | None]:
    """Return (session_key, friendly_label) for the calling CC session.

    The CC session is the user's TUI — the server runs as a daemon and
    doesn't share its process tree. So we fall back to reading the most
    recent .name sidecar from ~/.claude/quest/run/, which `cmd_claim`
    writes when the operator passes --session-name.

    For the explicit `bind` flow the client passes the name in the POST
    body, so this helper only matters as a fallback.
    """
    key = _quest.session_key()
    label = None
    if key:
        sidecar = _quest.claim_file_for(key).with_suffix(".name")
        if sidecar.exists():
            try:
                label = sidecar.read_text(encoding="utf-8").strip() or None
            except OSError:
                pass
    return key, label


def _do_mutate(project_id: str, quest_id: str, mutator) -> tuple[bool, str, list[str]]:
    """Run `mutator(quest_dict) -> None` under the write lock, atomic save, re-render.

    Returns (ok, message, new_tags_list)."""
    with _WRITE_LOCK:
        try:
            data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return False, f"failed to read quests.json: {e}", []
        q = _find_quest(data, project_id, quest_id)
        if not q:
            return False, f"quest not found: {project_id}/{quest_id}", []
        try:
            mutator(q)
        except ValueError as e:
            return False, str(e), q.get("tags", []) or []
        tags = q.get("tags") or []
        # Normalize: drop empties + dedup preserving order
        seen = set()
        clean = []
        for t in tags:
            t = (t or "").strip()
            if t and t not in seen:
                seen.add(t)
                clean.append(t)
        if clean:
            q["tags"] = clean
        elif "tags" in q:
            # Remove empty tags list to keep the JSON clean
            del q["tags"]
        _atomic_write_json(DATA_PATH, data)
        # Best-effort re-render — failures don't block the mutation response.
        try:
            _render.render_all()
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[server] render after mutation failed: {e}\n")
        return True, "ok", clean


class QuestHandler(SimpleHTTPRequestHandler):
    """Static GET + JSON POST API. Inherits directory listing & range support."""

    # SimpleHTTPRequestHandler quirk: `directory=` is set via constructor
    # arg — we override server_class to pass it. Cleaner to override
    # translate_path() here.
    def translate_path(self, path: str) -> str:
        # Strip /api/* — those never hit static.
        rel = path.split("?", 1)[0].split("#", 1)[0]
        if rel.startswith("/api/"):
            return ""  # forces 404 if not handled by do_POST/do_GET
        # Standard SimpleHTTPRequestHandler logic but rooted at SITE_DIR.
        # Easiest: cd into SITE_DIR (process cwd) — but that conflicts with
        # systemd. Instead, fake it:
        from urllib.parse import unquote
        rel = unquote(rel)
        parts = [p for p in rel.split("/") if p and p not in (".", "..")]
        return str(SITE_DIR.joinpath(*parts))

    # Silence the very noisy default logger; keep errors.
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        if args and isinstance(args[1], str) and args[1].startswith(("4", "5")):
            sys.stderr.write(
                "[server] %s - %s\n" % (self.address_string(), fmt % args)
            )

    # -------- GET --------
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/session":
            self._json(200, self._session_info())
            return
        # Fall through to static
        super().do_GET()

    # -------- POST --------
    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if not path.startswith("/api/"):
            self._json(404, {"error": "not found"})
            return
        # Read body
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"error": "invalid JSON body"})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "body must be a JSON object"})
            return

        if path == "/api/tags/add":
            self._handle_tag_add(body)
        elif path == "/api/tags/remove":
            self._handle_tag_remove(body)
        elif path == "/api/tags/bind":
            self._handle_bind(body)
        elif path == "/api/tags/unbind":
            self._handle_unbind(body)
        elif path == "/api/quest/rename":
            self._handle_rename(body)
        else:
            self._json(404, {"error": "unknown endpoint"})

    # -------- handlers --------
    def _handle_tag_add(self, body: dict) -> None:
        project = (body.get("project") or "").strip()
        quest_id = (body.get("id") or "").strip()
        tag_raw = body.get("tag") or ""
        # Allow comma-separated bulk: "foo,bar,baz"
        candidates = [_normalize_tag(t) for t in tag_raw.split(",")]
        clean = [t for t in candidates if t]
        if not project or not quest_id or not clean:
            self._json(400, {"error": "project, id, and at least one valid tag required"})
            return

        def mutate(q: dict) -> None:
            existing = list(q.get("tags") or [])
            for t in clean:
                if t not in existing:
                    existing.append(t)
            q["tags"] = existing

        ok, msg, tags = _do_mutate(project, quest_id, mutate)
        self._json(200 if ok else 400, {"ok": ok, "msg": msg, "tags": tags})

    def _handle_tag_remove(self, body: dict) -> None:
        project = (body.get("project") or "").strip()
        quest_id = (body.get("id") or "").strip()
        tag = (body.get("tag") or "").strip()
        if not project or not quest_id or not tag:
            self._json(400, {"error": "project, id, and tag required"})
            return

        def mutate(q: dict) -> None:
            q["tags"] = [t for t in (q.get("tags") or []) if t != tag]

        ok, msg, tags = _do_mutate(project, quest_id, mutate)
        self._json(200 if ok else 400, {"ok": ok, "msg": msg, "tags": tags})

    def _handle_bind(self, body: dict) -> None:
        project = (body.get("project") or "").strip()
        quest_id = (body.get("id") or "").strip()
        name_override = (body.get("name") or "").strip()
        if not project or not quest_id:
            self._json(400, {"error": "project and id required"})
            return
        # Prefer caller-supplied name (UI captures it from the input box);
        # fall back to the most recent .name sidecar; finally session_key.
        key, label = _session_label()
        chosen = name_override or label or (key or "")
        if not chosen:
            self._json(400, {"error": "no session name available"})
            return
        # Tag form: `session:<chosen>` — normalized like any other tag
        tag = _normalize_tag(f"session:{chosen}")
        if not tag:
            self._json(400, {"error": f"invalid session name: {chosen!r}"})
            return

        def mutate(q: dict) -> None:
            existing = list(q.get("tags") or [])
            if tag not in existing:
                existing.append(tag)
            q["tags"] = existing

        ok, msg, tags = _do_mutate(project, quest_id, mutate)
        self._json(200 if ok else 400, {"ok": ok, "msg": msg, "tags": tags, "tag": tag})

    def _handle_unbind(self, body: dict) -> None:
        project = (body.get("project") or "").strip()
        quest_id = (body.get("id") or "").strip()
        if not project or not quest_id:
            self._json(400, {"error": "project and id required"})
            return
        # Unbind removes ALL session:* tags whose value matches the current
        # session_key OR the current .name sidecar value. We're conservative —
        # we don't blindly delete every session:* (other sessions might own
        # them).
        key, label = _session_label()
        candidates = set()
        if key:
            candidates.add(_normalize_tag(f"session:{key}"))
        if label:
            candidates.add(_normalize_tag(f"session:{label}"))
        candidates.discard("")
        if not candidates:
            self._json(400, {"error": "no session identity to unbind"})
            return

        def mutate(q: dict) -> None:
            q["tags"] = [t for t in (q.get("tags") or []) if t not in candidates]

        ok, msg, tags = _do_mutate(project, quest_id, mutate)
        self._json(200 if ok else 400, {"ok": ok, "msg": msg, "tags": tags})

    def _handle_rename(self, body: dict) -> None:
        """POST /api/quest/rename — body {project, id, name}.
        Renames quest.name in quests.json (operator override; autosync never touches name).
        Re-renders all themes after save."""
        project = (body.get("project") or "").strip()
        quest_id = (body.get("id") or "").strip()
        new_name = (body.get("name") or "").strip()
        if not project or not quest_id:
            self._json(400, {"error": "project and id required"})
            return
        if not new_name:
            self._json(400, {"error": "name cannot be empty"})
            return
        if len(new_name) > 200:
            self._json(400, {"error": "name too long (max 200 chars)"})
            return

        old_name_box = {"v": None}

        def mutate(q: dict) -> None:
            old_name_box["v"] = q.get("name")
            q["name"] = new_name

        ok, msg, _ = _do_mutate(project, quest_id, mutate)
        if ok:
            self._json(200, {"ok": True, "msg": "renamed", "old_name": old_name_box["v"], "new_name": new_name})
        else:
            self._json(400, {"ok": False, "msg": msg})

    def _session_info(self) -> dict:
        key, label = _session_label()
        return {
            "session_key": key or "",
            "session_label": label or "",
            "session_tag": _normalize_tag(f"session:{label or key or ''}") if (label or key) else "",
        }

    # -------- helper --------
    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    host = os.environ.get("QUEST_HOST", "127.0.0.1")
    port = int(os.environ.get("QUEST_PORT", "8770"))
    # Best-effort first render so the site dir is populated.
    try:
        _render.render_all()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[server] initial render failed (non-fatal): {e}\n")
    server = ThreadingHTTPServer((host, port), QuestHandler)
    sys.stderr.write(f"[server] quest-dashboard up on http://{host}:{port}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("[server] shutting down\n")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
