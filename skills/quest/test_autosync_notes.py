#!/usr/bin/env python3
"""Tests: autosync notes-branch — sidecar edits re-render, never plan-parse.

Spec: ~/.claude/skills/quest/docs/specs/2026-05-14-quest-my-todo-design.md §6

When a file under quest/data/notes/ is written, the autosync hook forks
autosync.py with that path; autosync.py must take a RENDER-ONLY branch —
re-render the dashboard, skip all plan-parsing logic (no project detection,
no quest add/update, no quests.json mutation).

Run: python3 ~/.claude/skills/quest/test_autosync_notes.py
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).parent
AUTOSYNC = SKILL_DIR / "autosync.py"
QUEST = SKILL_DIR / "quest.py"
HOOK = Path.home() / ".claude" / "hooks" / "quest-plan-autosync.sh"


def setup_sandbox(tmp):
    root = Path(tmp)
    claude = root / ".claude"
    (claude / "quest" / "data" / "notes").mkdir(parents=True)
    (claude / "quest" / "run").mkdir(parents=True)
    (claude / "quest" / "site").mkdir(parents=True)
    (claude / "quest" / "logs").mkdir(parents=True)
    (claude / "skills").mkdir(parents=True)
    (claude / "skills" / "quest").symlink_to(SKILL_DIR)
    (claude / "quest" / "config.json").write_text('{"dashboard_url": "http://localhost:8770"}')
    return root


def run(home, script, *args):
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        ["python3", str(script), *args], env=env, capture_output=True, text=True, check=False
    )


def quests_json(home):
    return json.loads((home / ".claude" / "quest" / "data" / "quests.json").read_text())


def test_notes_path_renders_not_plan_parsed():
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run(home, QUEST, "init", "testproj", "--theme", "pokemon").check_returncode()
        run(home, QUEST, "add", "testproj", "Alpha").check_returncode()
        before = len(quests_json(home)["projects"]["testproj"]["quests"])

        notes = home / ".claude" / "quest" / "data" / "notes" / "testproj__alpha.md"
        notes.write_text("# My To-Do — Alpha\n\n- [ ] a user task\n")

        r = run(home, AUTOSYNC, str(notes))
        assert r.returncode == 0, f"stderr={r.stderr}"

        # quests.json untouched — no quest added/updated from a notes path
        after = len(quests_json(home)["projects"]["testproj"]["quests"])
        assert after == before, f"notes path mutated quests.json: {before} -> {after}"
        print("PASS: autosync on a notes path does NOT plan-parse / mutate quests.json")


def test_notes_path_triggers_render():
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run(home, QUEST, "init", "testproj", "--theme", "pokemon").check_returncode()
        run(home, QUEST, "add", "testproj", "Alpha").check_returncode()

        # Wipe the site dir so we can prove the notes write regenerated it.
        site = home / ".claude" / "quest" / "site"
        for p in site.rglob("*"):
            if p.is_file():
                p.unlink()

        notes = home / ".claude" / "quest" / "data" / "notes" / "testproj__alpha.md"
        notes.write_text("# My To-Do — Alpha\n\n- [ ] regenerate me\n")
        r = run(home, AUTOSYNC, str(notes))
        assert r.returncode == 0, f"stderr={r.stderr}"

        assert (site / "testproj" / "plan-card.html").exists(), "render did not run for notes write"
        log = (home / ".claude" / "quest" / "logs" / "autosync.log").read_text()
        assert "notes-triggered" in log, f"expected notes-triggered log line, got: {log!r}"
        print("PASS: autosync on a notes path re-renders the dashboard")


def test_hook_routes_notes_paths():
    """Structural: the hook's case statement matches quest/data/notes/*.md."""
    assert HOOK.exists(), f"hook missing: {HOOK}"
    body = HOOK.read_text()
    assert "quest/data/notes/" in body, "hook does not route quest/data/notes/*.md paths"
    print("PASS: quest-plan-autosync.sh routes quest/data/notes/*.md")


if __name__ == "__main__":
    test_notes_path_renders_not_plan_parsed()
    test_notes_path_triggers_render()
    test_hook_routes_notes_paths()
    print("\nAll 3 autosync notes-branch tests passed.")
