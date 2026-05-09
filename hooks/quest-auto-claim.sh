#!/bin/bash
# SessionStart hook — auto-claim a quest based on cwd + session_name.
#
# Reads stdin JSON for `.session_name` + `.cwd`, then runs `/quest claim`
# inline (~50ms). NOT backgrounded — backgrounding causes the bg subshell
# to be reparented away from the `claude` ancestor, breaking session_key
# resolution. SessionStart has a 5s timeout; 50ms is well under.
#
# Soft-fails on any error (no project resolvable, no quest, missing python)
# — logs to ~/.claude/quest/logs/auto-claim.log and exits 0 so CC proceeds.
set +eu

INPUT=$(timeout 1 cat 2>/dev/null || echo '{}')
SESSION_NAME=$(echo "$INPUT" | jq -r '.session_name // empty' 2>/dev/null)
CWD=$(echo "$INPUT" | jq -r '.cwd // .workspace.current_dir // empty' 2>/dev/null)
[ -z "$CWD" ] && CWD="$HOME"

LOG="$HOME/.claude/quest/logs/auto-claim.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null

ts=$(date -Iseconds 2>/dev/null || date)
out=$(cd "$CWD" 2>/dev/null && \
      python3 "$HOME/.claude/skills/quest/quest.py" claim \
        --session-name "$SESSION_NAME" 2>&1)
rc=$?
printf '[%s] cwd=%s session_name=%q rc=%d | %s\n' \
  "$ts" "$CWD" "$SESSION_NAME" "$rc" "$(echo "$out" | tr '\n' ' ')" >> "$LOG" 2>/dev/null || true

exit 0
