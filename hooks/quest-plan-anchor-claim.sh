#!/bin/bash
# Hook Type: PostToolUse (Write|Edit on plan files) — Plan-Anchored Auto-Claim.
#
# Deterministic successor to the disabled IDF guesser (quest-prompt-rebind.sh):
# when a plan file is written/edited, claim the quest whose `plan` field
# matches it — exact match only, never a guess. All policy (lock honoring
# WITHOUT unlink, exactly-one-current guard, idempotence, JSONL logging)
# lives in quest.py cmd_claim_plan; this hook only filters + dispatches.
#
# MUST run INLINE (not nohup/backgrounded): the claim needs the /proc walk
# to the live `claude` ancestor pid — backgrounding reparents the subshell
# and breaks session_key resolution (see quest-auto-claim.sh header).
# Inline cost ~60ms, well under the PostToolUse budget.
#
# Kill switches: QUEST_PLAN_ANCHOR_DISABLED=1
#                touch ~/.claude/quest/plan-anchor-disabled
# Observability: ~/.claude/quest/log/rebind.jsonl event=plan_anchor
# Plan: ~/.claude/plans/claim-discipline-troubleshooting-dynamic-brook.md
set +eu

if [ "${QUEST_PLAN_ANCHOR_DISABLED:-0}" = "1" ]; then exit 0; fi
if [ -f "$HOME/.claude/quest/plan-anchor-disabled" ]; then exit 0; fi

INPUT=$(timeout 1 cat 2>/dev/null || true)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -z "$FILE" ] && exit 0

case "$FILE" in
  */quest/data/notes/*.md) exit 0 ;;                  # My To-Do sidecars — never anchor
  */.claude/plans/*.md|*/plans/*.md) ;;               # plan files — proceed
  *) exit 0 ;;
esac

python3 "$HOME/.claude/skills/quest/quest.py" claim --plan "$FILE" \
  >/dev/null 2>&1 || true
exit 0
