"""Quest prompt-rebind scorer.

Hook worker invoked by ~/.claude/hooks/quest-prompt-rebind.sh on every
UserPromptSubmit. Reads JSON from stdin, scores the prompt against the
session's project's current quests using an IDF tokenizer with two-stage
logic (user-alone first, joined-with-prior-assistant-context as fallthrough),
and atomically rewrites the session's claim file when the signal is strong.

Designed empirically — see ~/.claude/skills/quest/test_prompt_rebind.py
for the 38-prompt regression corpus and ~/.claude/quest/log/rebind.jsonl
for live observability. Tune thresholds via /quest rebind-stats.

Failure modes are all soft: missing transcript, no current quests, empty
prompt, malformed config, lock file present, dry-run marker present — each
logs a reason and exits 0. The hook never blocks the prompt.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
QUEST_ROOT = HOME / ".claude" / "quest"
RUN_DIR = QUEST_ROOT / "run"
LOG_DIR = QUEST_ROOT / "log"
LOG_FILE = LOG_DIR / "rebind.jsonl"
DRY_RUN_MARKER = QUEST_ROOT / "dry-run"
DATA_FILE = QUEST_ROOT / "data" / "quests.json"
CONFIG_FILE = QUEST_ROOT / "config.json"

REBIND_SCORE = 5.0
REBIND_MARGIN = 5.0       # RC1: raised 3->5 — blocks low-margin user-alone noise rebinds
SUGGEST_SCORE = 3.0
USER_WEIGHT = 5.0
CONFLICT_OVERRIDE_FRAC = 0.4  # RC2: joined-top must dominate >=40% of total to override conflict guard
TRANSCRIPT_TAIL_BYTES = 200_000  # cap I/O on huge transcripts
TRANSCRIPT_SCAN_LINES = 50       # only scan last N lines for assistant msg

STOP = {
    "the", "and", "for", "from", "with", "this", "that", "any", "via",
    "quest", "plan", "add", "now", "its", "was", "are", "can", "let",
    "look", "should", "what", "when", "why", "how", "will", "you", "your",
    "our", "make", "need", "want", "have", "been", "lets", "also", "just",
    "here", "there", "use", "get", "put", "run", "show", "say", "one",
    "two", "time", "wait", "yes", "actually", "instead", "not", "more",
    "less", "very", "some", "all", "really", "would", "could", "might",
    "user", "assistant",
}


def _log(entry: dict) -> None:
    """Append-only JSONL log. Atomic append on Linux for <PIPE_BUF bytes."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _ts() -> str:
    return time.strftime("%FT%TZ", time.gmtime())


def _tok(s: str | None) -> list[str]:
    if not s:
        return []
    return [
        t for t in re.split(r"[^a-z0-9]+", s.lower())
        if len(t) >= 3 and t not in STOP
    ]


def _walk_claude_pid() -> str | None:
    """Resolve session_key by walking parent PIDs to find the claude process.

    Same algorithm as ~/.claude/skills/quest/quest.py session_key().
    Returns '<pid>-<starttime_ticks>' or None.
    """
    pid = os.getppid()
    for _ in range(40):
        if pid is None or pid <= 1:
            return None
        try:
            comm = (Path(f"/proc/{pid}/comm").read_text().strip())
        except Exception:
            return None
        if comm == "claude":
            try:
                raw = Path(f"/proc/{pid}/stat").read_text()
                # Strip the parenthesized comm field which may contain spaces.
                raw = re.sub(r"\(.*?\)", "X", raw, count=1)
                fields = raw.split()
                # field 22 (index 21) = starttime in clock ticks since boot
                ticks = fields[21]
                return f"{pid}-{ticks}"
            except Exception:
                return None
        try:
            raw = Path(f"/proc/{pid}/stat").read_text()
            raw = re.sub(r"\(.*?\)", "X", raw, count=1)
            fields = raw.split()
            pid = int(fields[3])  # ppid
        except Exception:
            return None
    return None


def _resolve_project(cwd: str) -> str:
    """Resolve cwd → project id via config.json path_map."""
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return ""
    candidates = config.get("path_map") or []
    for entry in sorted(candidates, key=lambda e: -len(e.get("path", ""))):
        p = entry.get("path", "")
        if not p:
            continue
        if cwd == p or cwd.startswith(p + "/") or cwd.startswith(p + "-") or cwd.startswith(p + "_"):
            return entry.get("id", "")
    return ""


def _read_prior_assistant_text(transcript_path: str) -> str:
    """Read the LAST assistant text block from transcript. Bounded I/O.

    Strategy:
      - If file >200KB: seek to len-200000, read tail.
      - Parse last 50 lines, find newest role=assistant with type=text block.
      - Cap at 1000 chars.
    Never raises — returns '' on any failure.
    """
    try:
        if not transcript_path:
            return ""
        path = Path(transcript_path)
        if not path.is_file():
            return ""
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > TRANSCRIPT_TAIL_BYTES:
                f.seek(size - TRANSCRIPT_TAIL_BYTES)
                f.readline()  # skip partial line
            tail = f.read().decode("utf-8", errors="replace")
        lines = tail.splitlines()[-TRANSCRIPT_SCAN_LINES:]
        for line in reversed(lines):
            try:
                d = json.loads(line)
            except Exception:
                continue
            msg = d.get("message") or {}
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if isinstance(content, list):
                parts = [
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                txt = " ".join(p for p in parts if p)
                if txt.strip():
                    return txt[:1000]
            elif isinstance(content, str) and content.strip():
                return content[:1000]
    except Exception:
        return ""
    return ""


def _score(p_tokens: set[str], docs: list[tuple[str, set[str]]], idf: dict[str, float]):
    """Return sorted (qid, score) list — highest first."""
    scored = []
    for qid, q_tok in docs:
        overlap = p_tokens & q_tok
        s = sum(idf.get(t, 0.0) for t in overlap)
        scored.append((qid, s))
    scored.sort(key=lambda x: -x[1])
    return scored


def _build_idf(quests: list[dict]) -> tuple[list[tuple[str, set[str]]], dict[str, float]]:
    df: dict[str, int] = {}
    docs: list[tuple[str, set[str]]] = []
    for q in quests:
        tok = set()
        fields = [
            q.get("id"), q.get("name"), q.get("desc"),
            q.get("branch", ""), q.get("next_step", ""),
        ]
        fields.extend(q.get("tags") or [])
        for f in fields:
            tok.update(_tok(f))
        docs.append((q["id"], tok))
        for t in tok:
            df[t] = df.get(t, 0) + 1
    n = len(quests) or 1
    idf = {t: math.log(1 + n / c) for t, c in df.items()}
    return docs, idf


def decide_action(prompt: str, prior_context: str, docs, idf):
    """Two-stage decision with conflict guard.

    1. Score user prompt alone (weight=USER_WEIGHT).
    2. If user-alone exceeds rebind threshold → rebind on user-top.
    3. Else score joined (user + prior_context).
    4. If user-top != joined-top AND user has SOME signal → suggest, not rebind.
    5. Else apply normal thresholds to joined score.

    Returns dict: {action, top, score, margin, runner, path, p_score, c_score}.
    """
    p_tok = set(_tok(prompt))
    c_tok = set(_tok(prior_context))

    # Stage 1: user-alone (no weight needed since we're not mixing)
    if p_tok:
        scored = _score(p_tok, docs, idf)
        u_top, u_score = scored[0]
        u_runner = scored[1][1] if len(scored) > 1 else 0
        u_margin = u_score - u_runner
        if u_score >= REBIND_SCORE and u_margin >= REBIND_MARGIN:
            return {
                "action": "rebind", "top": u_top, "score": round(u_score, 2),
                "margin": round(u_margin, 2), "runner": scored[1][0] if len(scored) > 1 else None,
                "path": "user-alone", "p_score": round(u_score, 2), "c_score": 0.0,
            }
    else:
        u_top = None
        u_score = 0.0

    # Stage 2: joined with USER_WEIGHT applied to user tokens
    if not (p_tok or c_tok):
        return {"action": "noop", "top": None, "score": 0.0, "margin": 0.0,
                "runner": None, "path": "no-tokens", "p_score": 0.0, "c_score": 0.0}

    scored_joined = []
    for qid, q_tok in docs:
        ps = sum(idf.get(t, 0.0) for t in (p_tok & q_tok)) * USER_WEIGHT
        cs = sum(idf.get(t, 0.0) for t in (c_tok & q_tok))
        scored_joined.append((qid, ps + cs, ps, cs))
    scored_joined.sort(key=lambda x: -x[1])
    j_top, j_total, j_p, j_c = scored_joined[0]
    j_runner = scored_joined[1] if len(scored_joined) > 1 else ("-", 0, 0, 0)
    j_margin = j_total - j_runner[1]

    # Conflict guard: user-prompt signals a DIFFERENT quest than joined picks
    if u_top and j_top != u_top and u_score >= SUGGEST_SCORE:
        # RC2: if joined-top overwhelmingly dominates the field AND the user's
        # own prompt signal is weak (below the rebind floor), the context is
        # decisive — rebind despite the conflict instead of only suggesting.
        # Scale-free: margin gated as a fraction of total, not an absolute
        # score, so it holds across corpora of any size.
        if (j_total > 0 and j_margin >= CONFLICT_OVERRIDE_FRAC * j_total
                and u_score < REBIND_SCORE):
            return {
                "action": "rebind", "top": j_top, "score": round(j_total, 2),
                "margin": round(j_margin, 2), "runner": j_runner[0],
                "path": "conflict-override", "p_score": round(j_p, 2),
                "c_score": round(j_c, 2), "user_top": u_top,
                "user_score": round(u_score, 2),
            }
        return {
            "action": "suggest", "top": j_top, "score": round(j_total, 2),
            "margin": round(j_margin, 2), "runner": j_runner[0],
            "path": "conflict", "p_score": round(j_p, 2), "c_score": round(j_c, 2),
            "user_top": u_top, "user_score": round(u_score, 2),
        }

    if j_total >= REBIND_SCORE and j_margin >= REBIND_MARGIN:
        return {
            "action": "rebind", "top": j_top, "score": round(j_total, 2),
            "margin": round(j_margin, 2), "runner": j_runner[0],
            "path": "joined", "p_score": round(j_p, 2), "c_score": round(j_c, 2),
        }
    if j_total >= SUGGEST_SCORE:
        return {
            "action": "suggest", "top": j_top, "score": round(j_total, 2),
            "margin": round(j_margin, 2), "runner": j_runner[0],
            "path": "joined-weak", "p_score": round(j_p, 2), "c_score": round(j_c, 2),
        }
    return {"action": "noop", "top": j_top, "score": round(j_total, 2),
            "margin": round(j_margin, 2), "runner": j_runner[0],
            "path": "below-suggest", "p_score": round(j_p, 2), "c_score": round(j_c, 2)}


def run_from_stdin() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        return 0

    prompt = (data.get("prompt") or "").strip()
    cwd = data.get("cwd") or (data.get("workspace") or {}).get("current_dir") or os.getcwd()
    transcript_path = data.get("transcript_path") or ""
    if not prompt:
        return 0

    sk = _walk_claude_pid()
    if not sk:
        _log({"ts": _ts(), "sk": "", "action": "skip", "acted": "no-sk",
              "prompt": prompt[:80]})
        return 0

    # RC4: <task-notification> blobs are harness-injected subagent completion
    # messages, not user intent — they must never drive a quest rebind.
    if prompt.startswith("<task-notification>"):
        _log({"ts": _ts(), "sk": sk, "action": "skip",
              "acted": "skipped_task_notification", "prompt": prompt[:80]})
        return 0

    # URL-lock sentinel check: when ~/.claude/hooks/quest-url-rebind.sh just
    # hard-rebound the claim via plan-card URL paste, short-circuit both rebind
    # and suggest paths for 60s. Prevents IDF token overlap from silently
    # undoing the operator's explicit URL paste in the same turn.
    # Companion: feedback_quest_reclaim_on_topic_shift_2026-05-15.md.
    url_lock_file = RUN_DIR / f"session-{sk}.url-locked"
    if url_lock_file.is_file():
        try:
            expiry = int(url_lock_file.read_text(encoding="utf-8").strip())
            if expiry > time.time():
                _log({"ts": _ts(), "sk": sk, "action": "skip",
                      "acted": "skipped_url_locked", "expiry": expiry,
                      "prompt": prompt[:80]})
                return 0
            url_lock_file.unlink(missing_ok=True)
        except Exception:
            pass

    project = _resolve_project(cwd)
    if not project:
        _log({"ts": _ts(), "sk": sk, "action": "skip", "acted": "no-project",
              "cwd": cwd, "prompt": prompt[:80]})
        return 0

    try:
        qdata = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return 0
    quests = [
        q for q in (qdata.get("projects", {}).get(project, {}).get("quests") or [])
        if q.get("status") == "current"
    ]
    if not quests:
        _log({"ts": _ts(), "sk": sk, "project": project, "action": "skip",
              "acted": "no-current-quests", "prompt": prompt[:80]})
        return 0

    docs, idf = _build_idf(quests)
    prior = _read_prior_assistant_text(transcript_path)
    decision = decide_action(prompt, prior, docs, idf)

    action = decision["action"]
    top = decision.get("top")
    claim_file = RUN_DIR / f"session-{sk}.quest"
    current = ""
    if claim_file.is_file():
        try:
            current = claim_file.read_text(encoding="utf-8").strip()
        except Exception:
            current = ""
    new_claim = f"{project}/{top}" if top else ""

    acted = action
    if action == "rebind" and top:
        if new_claim == current:
            acted = "rebound-noop-same"
        elif (claim_file.with_suffix(".quest.lock")).exists() or (claim_file.parent / f"{claim_file.name}.lock").exists():
            acted = "locked-skip"
        elif DRY_RUN_MARKER.exists():
            acted = "rebound-dryrun"
        else:
            try:
                RUN_DIR.mkdir(parents=True, exist_ok=True)
                tmp = tempfile.NamedTemporaryFile(
                    "w", dir=str(RUN_DIR), delete=False, encoding="utf-8"
                )
                tmp.write(new_claim + "\n")
                tmp.close()
                os.rename(tmp.name, str(claim_file))
                acted = "rebound"
            except Exception as e:
                acted = f"error:{type(e).__name__}"

    log_entry = {
        "ts": _ts(), "sk": sk, "project": project, "action": action,
        "acted": acted, "top": top, "score": decision.get("score", 0.0),
        "margin": decision.get("margin", 0.0), "runner": decision.get("runner"),
        "p_score": decision.get("p_score", 0.0), "c_score": decision.get("c_score", 0.0),
        "path": decision.get("path"), "from": current, "prompt": prompt[:80],
        "ctx_len": len(prior),
    }
    if "user_top" in decision:
        log_entry["user_top"] = decision["user_top"]
        log_entry["user_score"] = decision["user_score"]
    _log(log_entry)

    # Surface suggest as additionalContext (stdout from UserPromptSubmit hook injects).
    if action == "suggest" and top:
        cur_id = current.split("/", 1)[1] if "/" in current else ""
        if top != cur_id:
            print(
                f"[quest-hint] prompt could be quest '{top}' "
                f"(s={decision.get('score', 0):.1f} m={decision.get('margin', 0):.1f}); "
                f"claim={current or 'none'}. "
                f"`/quest claim {project} {top}` to switch."
            )
    return 0


if __name__ == "__main__":
    sys.exit(run_from_stdin())
