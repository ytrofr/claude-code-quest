#!/bin/bash
# Hook Type: PostToolUse (async)
# Fires when a plan file is written/edited; forks autosync.py and exits.
# NEVER blocks: <5ms target, swallows all errors.
#
# Triggers on Write/Edit to:
#   - ~/.claude/plans/*.md
#   - <project>/plans/*.md
#   - <project>/.claude/plans/*.md
#   - ~/.claude/quest/data/notes/*.md  (My To-Do sidecar — autosync render-only branch)

INPUT=$(timeout 1 cat 2>/dev/null || true)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

case "$FILE" in
  */.claude/plans/*.md|*/plans/*.md) ;;
  */quest/data/notes/*.md) ;;
  *) exit 0 ;;
esac

# Fire-and-forget: fork autosync, log all output, return immediately.
mkdir -p "$HOME/.claude/quest/logs" "$HOME/.claude/quest/run" 2>/dev/null
nohup python3 "$HOME/.claude/skills/quest/autosync.py" "$FILE" \
  >>"$HOME/.claude/quest/logs/autosync.log" 2>&1 & disown
exit 0
