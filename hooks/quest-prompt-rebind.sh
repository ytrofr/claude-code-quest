#!/bin/bash
# UserPromptSubmit hook: auto-rebind the quest claim file based on the prompt.
#
# Reads JSON from stdin {prompt, cwd, transcript_path, session_id}, pipes it
# to the Python scorer which does /proc walk + project resolution + IDF scoring
# + atomic claim file rewrite. Fire-and-forget per kill switches:
#   - touch ~/.claude/quest/dry-run    → log decisions but never rewrite claim
#   - touch ~/.claude/quest/run/session-<sk>.quest.lock → freeze this session
#
# Output: scorer emits "[quest-hint] ..." line to stdout when action=suggest,
# which CC injects as additionalContext for the response. Other actions are
# silent (claim file rewrite is the side effect).
#
# Latency budget: ~120-200ms median. Never blocks: any failure exits 0.
#
# Hard kill: rename this file to .disabled, or remove from settings.json hooks.
# Logs: ~/.claude/quest/log/rebind.jsonl (used by /quest rebind-stats).
#
# Spec: ~/.claude/skills/quest/prompt_rebind_scorer.py module docstring.

# Master kill switch — flip without editing settings.json
if [ -f "$HOME/.claude/quest/prompt-rebind-disabled" ]; then
  exit 0
fi

SCORER="$HOME/.claude/skills/quest/prompt_rebind_scorer.py"
[ ! -r "$SCORER" ] && exit 0

# Pass stdin through to the scorer. Cap to 2s total — scorer itself bounds I/O,
# but the timeout is a belt-and-suspenders safeguard against unexpected hangs.
exec timeout 2 python3 "$SCORER"
