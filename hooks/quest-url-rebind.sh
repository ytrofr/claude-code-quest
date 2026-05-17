#!/bin/bash
# UserPromptSubmit hook: detect plan-card URL paste and hard-rebind the quest claim.
#
# When the operator pastes localhost:8770/<proj>/plan-card.html?q=<qid> in chat,
# this hook bypasses the model's "did I notice?" judgment and DIRECTLY claims
# the quest for THIS session. Three deterministic side effects:
#
#   1. Invoke `python3 ~/.claude/skills/quest/quest.py claim <proj> <qid>` —
#      preserves validation, sidecars (.lock, .name), dead-session GC,
#      claimed_session_name write-back to quests.json. NEVER direct-write the
#      claim file; the CLI is the canonical write path.
#   2. Write session-<sk>.url-locked (60s expiry-epoch in file content). The
#      prompt-rebind scorer reads this and short-circuits to prevent IDF token
#      overlap from undoing the operator's URL paste in the same turn.
#   3. Write session-<sk>.canary-suppressed-until (5min expiry-epoch). The
#      statusline reads this and suppresses the ⚠ drift glyph because the
#      mismatch is INTENTIONAL (operator just hard-rebound).
#
# Also emit additionalContext directing Claude to Read the plan file first.
# Plan path is resolved from quests.json `quest.plan` (full absolute path).
#
# Always exit 0 — UserPromptSubmit cannot block; behavior is side-effect + context.
# Kill switch: QUEST_URL_AUTOCLAIM_DISABLED=1 or touch ~/.claude/quest/url-autoclaim-disabled.
# Logs: ~/.claude/quest/log/rebind.jsonl with event=url_autoclaim / url_autoclaim_failed.
#
# Companion: ~/.claude/skills/quest/prompt_rebind_scorer.py (sentinel check),
#            ~/.claude/scripts/statusline-quest.sh (canary suppression check).
# Plan: ~/.claude/plans/i-want-to-plan-piped-candle.md (Task 2).
# Rule: ~/.claude/projects/-home-ytr/memory/feedback_quest_reclaim_on_topic_shift_2026-05-15.md.

set +eu

# Kill switches (master + per-call)
if [ "${QUEST_URL_AUTOCLAIM_DISABLED:-0}" = "1" ]; then exit 0; fi
if [ -f "$HOME/.claude/quest/url-autoclaim-disabled" ]; then exit 0; fi

# Read stdin JSON (per hook-stdin-pattern.md — never env vars)
INPUT=$(timeout 2 cat 2>/dev/null || true)
[ -z "$INPUT" ] && exit 0

PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // empty' 2>/dev/null)
[ -z "$PROMPT" ] && exit 0

# URL detection — match anywhere in prompt (fenced or not).
# Per plan §11 Open Questions: operator intent dominates context.
# Extended regex; first match wins (head -1). Underscore allowed in qid
# per the existing skill SKILL.md regex on line ~111.
URL_LINE=$(printf '%s' "$PROMPT" | grep -oE 'localhost:8770/[a-z][a-z0-9_-]*/plan-card\.html\?q=[a-z0-9_-]+' 2>/dev/null | head -1)
[ -z "$URL_LINE" ] && exit 0

# Extract project + qid via sed (regex same as detection)
PROJECT=$(printf '%s' "$URL_LINE" | sed -E 's|^localhost:8770/([a-z][a-z0-9_-]*)/.*|\1|')
QID=$(printf '%s' "$URL_LINE" | sed -E 's|.*\?q=([a-z0-9_-]+).*|\1|')

[ -z "$PROJECT" ] || [ -z "$QID" ] && exit 0

# Resolve session_key via /proc walk — same algorithm as statusline-quest.sh
# and quest.py session_key(). Combine claude PID + raw field-22 starttime ticks
# (per ~/.claude/rules/technical/wsl2-proc-btime-drift.md — raw ticks, not btime+ticks/HZ).
SK=""
pid=$$
depth=0
while [ "$depth" -lt 40 ] && [ -n "$pid" ] && [ "$pid" -gt 1 ] 2>/dev/null; do
  comm=""
  [ -r "/proc/$pid/comm" ] && comm=$(cat "/proc/$pid/comm" 2>/dev/null)
  if [ "$comm" = "claude" ]; then
    stat=$(sed 's/([^)]*)/X/' "/proc/$pid/stat" 2>/dev/null)
    ticks=$(printf '%s' "$stat" | awk '{print $22}')
    [ -n "$ticks" ] && SK="${pid}-${ticks}"
    break
  fi
  stat=$(sed 's/([^)]*)/X/' "/proc/$pid/stat" 2>/dev/null)
  [ -z "$stat" ] && break
  ppid=$(printf '%s' "$stat" | awk '{print $4}')
  [ -z "$ppid" ] || [ "$ppid" = "0" ] && break
  pid="$ppid"
  depth=$((depth + 1))
done

[ -z "$SK" ] && exit 0

RUN_DIR="$HOME/.claude/quest/run"
LOG_FILE="$HOME/.claude/quest/log/rebind.jsonl"
DATA_FILE="$HOME/.claude/quest/data/quests.json"
TS=$(date -u +%FT%TZ)
PROMPT_LEN=${#PROMPT}

mkdir -p "$RUN_DIR" "$(dirname "$LOG_FILE")" 2>/dev/null

# Invoke canonical claim CLI. Preserves all sidecar writes + validation.
CLAIM_OUTPUT=$(python3 "$HOME/.claude/skills/quest/quest.py" claim "$PROJECT" "$QID" 2>&1)
CLAIM_RC=$?

if [ "$CLAIM_RC" -ne 0 ]; then
  # Log failure to jsonl; emit hint so operator sees something happened
  ERR_SHORT=$(printf '%s' "$CLAIM_OUTPUT" | head -c 200 | tr '\n' ' ' | sed 's/"/\\"/g')
  printf '{"ts":"%s","sk":"%s","event":"url_autoclaim_failed","claim_proj":"%s","claim_qid":"%s","rc":%d,"err":"%s","prompt_chars":%d}\n' \
    "$TS" "$SK" "$PROJECT" "$QID" "$CLAIM_RC" "$ERR_SHORT" "$PROMPT_LEN" >> "$LOG_FILE" 2>/dev/null
  printf '[quest-url] Tried to auto-claim %s/%s via URL paste but `quest.py claim` failed (rc=%d): %s\n' \
    "$PROJECT" "$QID" "$CLAIM_RC" "$ERR_SHORT"
  exit 0
fi

# Write sentinels (expiry-epoch in file content)
NOW=$(date +%s)
URL_LOCK_UNTIL=$((NOW + 60))
CANARY_UNTIL=$((NOW + 300))
printf '%s\n' "$URL_LOCK_UNTIL" > "$RUN_DIR/session-$SK.url-locked" 2>/dev/null
printf '%s\n' "$CANARY_UNTIL" > "$RUN_DIR/session-$SK.canary-suppressed-until" 2>/dev/null

# Resolve plan path from quests.json
PLAN_PATH=$(jq -r --arg p "$PROJECT" --arg q "$QID" \
  '(.projects[$p].quests // []) | map(select(.id == $q)) | .[0].plan // ""' \
  "$DATA_FILE" 2>/dev/null)

# Get quest status — if 'done' or 'locked', surface it
QUEST_STATUS=$(jq -r --arg p "$PROJECT" --arg q "$QID" \
  '(.projects[$p].quests // []) | map(select(.id == $q)) | .[0].status // ""' \
  "$DATA_FILE" 2>/dev/null)

# Log success
PLAN_PATH_ESC=$(printf '%s' "$PLAN_PATH" | sed 's/"/\\"/g')
printf '{"ts":"%s","sk":"%s","event":"url_autoclaim","claim_proj":"%s","claim_qid":"%s","plan_path":"%s","status":"%s","prompt_chars":%d,"url_lock_until":%d,"canary_until":%d}\n' \
  "$TS" "$SK" "$PROJECT" "$QID" "$PLAN_PATH_ESC" "$QUEST_STATUS" "$PROMPT_LEN" "$URL_LOCK_UNTIL" "$CANARY_UNTIL" >> "$LOG_FILE" 2>/dev/null

# Emit additionalContext directive (stdout from UserPromptSubmit hook = additionalContext)
# Status note: if quest is done/locked, flag it so the model addresses the discrepancy
STATUS_NOTE=""
if [ -n "$QUEST_STATUS" ] && [ "$QUEST_STATUS" != "current" ]; then
  STATUS_NOTE=" Note: this quest is status='$QUEST_STATUS' (not 'current') — confirm with the operator before extending or recreating."
fi

if [ -n "$PLAN_PATH" ] && [ -f "$PLAN_PATH" ]; then
  printf '[quest-url] Auto-claimed %s/%s via URL paste. FIRST tool call MUST be Read on %s — the plan content is NOT yet in context.%s\n' \
    "$PROJECT" "$QID" "$PLAN_PATH" "$STATUS_NOTE"
elif [ -n "$PLAN_PATH" ]; then
  printf '[quest-url] Auto-claimed %s/%s via URL paste. Plan file referenced at %s but missing on disk — proceed with quest record only.%s\n' \
    "$PROJECT" "$QID" "$PLAN_PATH" "$STATUS_NOTE"
else
  printf '[quest-url] Auto-claimed %s/%s via URL paste. No plan file linked in quests.json — proceed with quest record only.%s\n' \
    "$PROJECT" "$QID" "$STATUS_NOTE"
fi

exit 0
