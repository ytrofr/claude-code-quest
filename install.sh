#!/usr/bin/env bash
# claude-code-quest installer — one-shot bootstrap.
#
# What it does:
#   1. Copies skill source to ~/.claude/skills/quest/
#   2. Copies hook script to ~/.claude/hooks/quest-plan-autosync.sh
#   3. Drops example data + config (only if user has none yet)
#   4. Symlinks systemd unit + enables service on Linux
#   5. Prints next steps
#
# Idempotent — safe to run multiple times.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CC_DIR="${HOME}/.claude"
QUEST_DIR="${CC_DIR}/quest"

say() { printf "  \033[36m→\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$*" >&2; }
ok() { printf "  \033[32m✓\033[0m %s\n" "$*"; }

[ -d "${CC_DIR}" ] || { warn "~/.claude/ not found. Install Claude Code first: https://docs.claude.com/en/docs/claude-code"; exit 1; }

say "1/5 Installing skill source"
mkdir -p "${CC_DIR}/skills/quest"
cp -r "${REPO_DIR}/skills/quest/." "${CC_DIR}/skills/quest/"
ok "skill at ~/.claude/skills/quest/"

say "2/5 Installing plan-write hook"
mkdir -p "${CC_DIR}/hooks"
cp "${REPO_DIR}/hooks/quest-plan-autosync.sh" "${CC_DIR}/hooks/"
chmod +x "${CC_DIR}/hooks/quest-plan-autosync.sh"
ok "hook at ~/.claude/hooks/quest-plan-autosync.sh"
warn "Register the hook manually in ~/.claude/settings.json under hooks.PostToolUse — see README §Wiring the hook."

say "3/5 Bootstrapping data + config (only if missing)"
mkdir -p "${QUEST_DIR}/data"
if [ ! -f "${QUEST_DIR}/data/quests.json" ]; then
    cp "${REPO_DIR}/examples/quests.json" "${QUEST_DIR}/data/quests.json"
    ok "starter quests.json (apollo, atlas, nova) installed"
else
    ok "existing quests.json preserved"
fi
if [ ! -f "${QUEST_DIR}/config.json" ]; then
    cp "${REPO_DIR}/examples/config.json" "${QUEST_DIR}/config.json"
    ok "config.json template installed — EDIT to add your real project paths"
else
    ok "existing config.json preserved"
fi

say "4/5 Initial render"
python3 "${CC_DIR}/skills/quest/render.py" || warn "render failed — check above"

say "5/5 systemd service (Linux only — skipped on macOS / WSL without systemd)"
if command -v systemctl >/dev/null 2>&1 && systemctl --user >/dev/null 2>&1; then
    SYSD_DIR="${HOME}/.config/systemd/user"
    mkdir -p "${SYSD_DIR}"
    cp "${REPO_DIR}/systemd/quest-dashboard.service" "${SYSD_DIR}/quest-dashboard.service"
    systemctl --user daemon-reload
    systemctl --user enable --now quest-dashboard.service
    sleep 1
    if curl -fsS "http://localhost:8770/" -o /dev/null; then
        ok "dashboard live at http://localhost:8770"
    else
        warn "dashboard service installed but not responding — check 'systemctl --user status quest-dashboard'"
    fi
else
    warn "systemctl --user unavailable. To serve manually:"
    warn "  python3 -m http.server 8770 --directory ~/.claude/quest/site --bind 127.0.0.1"
fi

echo
ok "Installed. Next steps:"
echo "    1. Edit ~/.claude/quest/config.json with your real project paths"
echo "    2. Register the hook in ~/.claude/settings.json (README §Wiring)"
echo "    3. Open http://localhost:8770/"
echo "    4. /quest status   # or:  python3 ~/.claude/skills/quest/quest.py status"
