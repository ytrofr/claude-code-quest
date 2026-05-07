# Adding Projects

After install, you have three example projects (apollo, atlas, nova). To add your real ones:

## 1. Initialize the project entry

```bash
python3 ~/.claude/skills/quest/quest.py init <id>
# Example:
python3 ~/.claude/skills/quest/quest.py init myproject
```

This appends a stub project to `~/.claude/quest/data/quests.json`.

## 2. Wire the path map

Edit `~/.claude/quest/config.json` and add your project's absolute path:

```json
{
  "path_map": [
    {"path": "/home/me/myproject", "id": "myproject"}
  ]
}
```

**Order matters** — list more-specific paths first. The autosync hook walks this list top-to-bottom and uses the first matching prefix.

## 3. (Optional) Drop a pointer in the project

```bash
mkdir -p /home/me/myproject/.claude
cat > /home/me/myproject/.claude/quest-link.md <<'EOF'
# Quest Link
- Dashboard: http://localhost:8770/myproject/
- Project ID: `myproject`
- Source of truth: `~/.claude/quest/data/quests.json`
- Open with: `/quest status` or visit URL above
EOF
```

This is a human-facing breadcrumb — Claude doesn't need it, but it tells future-you where to find the dashboard for this project.

## 4. Add quests

Either:

**Manual**: `python3 ~/.claude/skills/quest/quest.py add myproject "Quest name" --landmark tower --plan myplan.md --next "do this"`

**Automatic**: write a plan file at `~/.claude/plans/myproject-feature.md` with a BLUF line:
```markdown
**Project**: myproject
```

The autosync hook resolves project from BLUF first, then path map, then current working directory. If it finds a match, the plan auto-appears as a quest. As you check `- [x]` boxes in the plan's `## Section 13 — Post-Validation`, the quest's progress and tasks update automatically.

## 5. Re-render and view

```bash
python3 ~/.claude/skills/quest/quest.py render
```

Open <http://localhost:8770/myproject/>.

## Removing a project

Edit `~/.claude/quest/data/quests.json` and delete the project's entry. Re-render. Done. (No formal `/quest remove` yet — coming in v1.2.)
