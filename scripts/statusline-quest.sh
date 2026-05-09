#!/bin/bash
# Statusline helper: emit the OSC-8-wrapped quest indicator field for the
# current CC session. Called from statusline.sh as `quest_indicator [<cwd>]`.
#
# Resolution order (hybrid):
#   1. Explicit claim — ~/.claude/quest/run/session-<key>.quest (written by
#      `/quest claim`). Format: "<project>/<quest-id>".
#   2. Auto-detect — cwd → path_map → most-recently-touched current quest.
#   3. Project home — cwd resolves a project but no current quest.
#   4. Dashboard root — no project resolvable.
#
# Output: OSC-8 hyperlink: ESC]8;;URL ESC\TAG ESC]8;; ESC\
# Modern terminals render TAG as a clickable link to URL. Bare xterm shows
# the raw escapes (degraded but not broken — set QUEST_STATUSLINE_NO_OSC8=1
# to disable).
#
# Created: 2026-05-09 (CC session ↔ quest binding for statusline).
set +eu

_qd_kebab() {
  # Kebab-case a free-form string: lowercase, non-alnum → "-", collapse runs,
  # trim leading/trailing hyphens. Used to compare CC --name to quest id.
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9]/-/g; s/--*/-/g; s/^-//; s/-$//'
}

quest_indicator() {
  local cwd="${1:-${PWD:-}}"
  local session_name="${2:-}"
  local data="$HOME/.claude/quest/data/quests.json"
  local config="$HOME/.claude/quest/config.json"
  local run_dir="$HOME/.claude/quest/run"
  local dashboard="${QUEST_DASHBOARD_URL:-http://localhost:8770}"

  # Resolve session key — same algorithm as quest.py session_key()
  # Walk up parent processes, find first ancestor with comm == "claude",
  # combine its pid + raw starttime ticks (field 22 of /proc/<pid>/stat).
  local sk=""
  local pid=$$ depth=0
  while [ "$depth" -lt 40 ] && [ -n "$pid" ] && [ "$pid" -gt 1 ] 2>/dev/null; do
    local comm=""
    [ -r "/proc/$pid/comm" ] && comm=$(cat "/proc/$pid/comm" 2>/dev/null)
    if [ "$comm" = "claude" ]; then
      local stat
      stat=$(sed 's/([^)]*)/X/' "/proc/$pid/stat" 2>/dev/null)
      local ticks
      ticks=$(printf '%s' "$stat" | awk '{print $22}')
      [ -n "$ticks" ] && sk="${pid}-${ticks}"
      break
    fi
    # Read ppid from stat field 4 (after stripping comm parens)
    local stat ppid
    stat=$(sed 's/([^)]*)/X/' "/proc/$pid/stat" 2>/dev/null)
    [ -z "$stat" ] && break
    ppid=$(printf '%s' "$stat" | awk '{print $4}')
    [ -z "$ppid" ] || [ "$ppid" = "0" ] && break
    pid="$ppid"
    depth=$((depth + 1))
  done

  # Tier 1: explicit claim
  local project="" qid=""
  if [ -n "$sk" ] && [ -r "$run_dir/session-$sk.quest" ]; then
    local claim
    claim=$(head -c 256 "$run_dir/session-$sk.quest" 2>/dev/null | tr -d '\r\n')
    project="${claim%%/*}"
    qid="${claim#*/}"
    [ "$project" = "$qid" ] && qid=""  # malformed file
  fi

  # Tier 2: auto-detect from cwd (only if no explicit claim).
  # Match a path_map prefix when cwd is exactly the prefix OR starts with
  # `prefix` followed by a separator (`/`, `-`, `_`). Lets one entry like
  # `~/MyApp` match all sibling worktrees (`MyApp-feature`, `MyApp-staging`,
  # `MyApp/sub/dir`) while still rejecting `MyApp2` / `MyAppXYZ`.
  if [ -z "$project" ] && [ -r "$config" ]; then
    project=$(jq -r --arg cwd "$cwd" '
      .path_map // [] | map(select(.path as $p |
        $cwd == $p
        or ($cwd | startswith($p + "/"))
        or ($cwd | startswith($p + "-"))
        or ($cwd | startswith($p + "_"))
      )) | sort_by(.path | length) | reverse | .[0].id // empty
    ' "$config" 2>/dev/null)
  fi

  # Validate the resolved project actually exists in quests.json. Without this,
  # an aspirational path_map entry (e.g. claude-code-guide → "guide") emits a
  # 404-prone tag like `quest: guide/-`. Fall through to dashboard root.
  if [ -n "$project" ] && [ -r "$data" ]; then
    local _proj_exists
    _proj_exists=$(jq -r --arg p "$project" 'if .projects[$p] then "yes" else "no" end' "$data" 2>/dev/null)
    if [ "$_proj_exists" != "yes" ]; then
      project=""
      qid=""
    fi
  fi

  # If we have a project but no qid, try most-recent-current quest
  if [ -n "$project" ] && [ -z "$qid" ] && [ -r "$data" ]; then
    qid=$(jq -r --arg p "$project" '
      .projects[$p].quests // [] |
      map(select(.status == "current")) |
      sort_by(.last_touched // "") | reverse | .[0].id // empty
    ' "$data" 2>/dev/null)
  fi

  # Build URL + tag. Session name appended (kebab-cased) when it differs from
  # the quest id — gives the user "what session am I in" + "what plan am I on"
  # in one line. Same value or absent → just the quest id (no duplicate).
  local url tag base sname_slug suffix=""
  if [ -n "$session_name" ]; then
    sname_slug=$(_qd_kebab "$session_name")
  else
    sname_slug=""
  fi
  if [ -n "$project" ] && [ -n "$qid" ]; then
    url="$dashboard/$project/plan-card.html?q=$qid"
    base="$project/$qid"
    if [ -n "$sname_slug" ] && [ "$sname_slug" != "$qid" ]; then
      suffix=" · $sname_slug"
    fi
    # Tag = bare project/qid + optional session suffix. URL is in the OSC-8
    # hyperlink escape (one-click on modern terminals); plaintext URL trailer
    # dropped to keep line 2 short enough for narrow terminals.
    tag="${base}${suffix}"
  elif [ -n "$project" ]; then
    url="$dashboard/$project/"
    base="$project/-"
    [ -n "$sname_slug" ] && suffix=" · $sname_slug"
    tag="${base}${suffix}"
  else
    url="$dashboard/"
    base="-"
    [ -n "$sname_slug" ] && suffix=" · $sname_slug"
    tag="${base}${suffix}"
  fi

  # OSC-8 hyperlink wrap (or plain tag if disabled)
  if [ -n "$QUEST_STATUSLINE_NO_OSC8" ]; then
    printf '%s' "$tag"
  else
    # OSC-8: ESC]8;;URL ST  TAG  ESC]8;; ST   (ST = ESC \)
    printf '\033]8;;%s\033\\%s\033]8;;\033\\' "$url" "$tag"
  fi
}

# If sourced, just expose the function. If executed directly, run it.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  quest_indicator "$@"
  echo
fi
