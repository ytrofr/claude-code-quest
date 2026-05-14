#!/usr/bin/env python3
"""Structural tests: the three-layer "know it by heart" integration.

Spec: ~/.claude/skills/quest/docs/specs/2026-05-14-quest-my-todo-design.md §8, §11 Tier 3

These assert the integration TEXT exists — necessary, not sufficient (the
behavioral probe in task #14 covers actual triggering). Layers:
  1. always-on rule  ~/.claude/rules/projects/quest-dashboard.md
  2. skill           ~/.claude/skills/quest/SKILL.md
  3. routines        (inside SKILL.md — Resume Routine step + Backlog Read Routine)

Run: python3 ~/.claude/skills/quest/test_integration_structural.py
"""
from pathlib import Path

RULE = Path.home() / ".claude" / "rules" / "projects" / "quest-dashboard.md"
SKILL = Path(__file__).parent / "SKILL.md"


def _skip_if_no_rule() -> bool:
    """The always-on rule is part of the user's ~/.claude setup, not shipped in
    this engine repo. On a fresh clone it won't exist — skip the rule-layer
    checks gracefully (SKILL.md checks still run)."""
    if not RULE.exists():
        print(f"SKIP: always-on rule not present ({RULE}) — not part of the engine repo")
        return True
    return False


def test_rule_documents_sidecar_path():
    if _skip_if_no_rule():
        return
    body = RULE.read_text(encoding="utf-8")
    assert "quest/data/notes/" in body, "always-on rule must name the sidecar path"
    assert "autosync-immune" in body or "autosync never" in body.lower(), (
        "rule must state the sidecar is autosync-immune"
    )
    print("PASS: always-on rule documents the sidecar path + autosync-immunity")


def test_rule_has_todo_write_triggers():
    if _skip_if_no_rule():
        return
    body = RULE.read_text(encoding="utf-8").lower()
    assert "todo add" in body, "rule must carry the `todo add` trigger"
    assert "remind me" in body, "rule must carry the 'remind me to X on quest Y' trigger"
    print("PASS: always-on rule has the todo-write NL triggers")


def test_rule_has_backlog_read_triggers():
    if _skip_if_no_rule():
        return
    body = RULE.read_text(encoding="utf-8").lower()
    for phrase in ("backlog", "task list", "what's left"):
        assert phrase in body, f"rule missing backlog-read trigger phrase: {phrase!r}"
    print("PASS: always-on rule has the backlog-read NL triggers")


def test_skill_has_my_todo_section():
    body = SKILL.read_text(encoding="utf-8")
    assert "My To-Do" in body, "SKILL.md must have a My To-Do section"
    assert "quest/data/notes/" in body, "SKILL.md must document the sidecar path"
    for cmd in ("todo add", "todo done", "todo undone", "todo rm",
                "todo note", "todo list", "todo edit"):
        assert cmd in body, f"SKILL.md missing `{cmd}` documentation"
    print("PASS: SKILL.md documents the My To-Do section + all 7 todo subcommands")


def test_skill_has_backlog_read_routine():
    body = SKILL.read_text(encoding="utf-8")
    assert "Backlog Read Routine" in body, "SKILL.md must have a Backlog Read Routine section"
    print("PASS: SKILL.md has the Backlog Read Routine section")


def test_skill_resume_routine_reads_sidecar():
    body = SKILL.read_text(encoding="utf-8")
    assert "Resume Routine" in body, "SKILL.md must still have the Resume Routine"
    assert "open to-dos" in body, (
        "Resume Routine must surface the user's open to-dos (sidecar read step)"
    )
    print("PASS: SKILL.md Resume Routine surfaces the sidecar's open to-dos")


if __name__ == "__main__":
    test_rule_documents_sidecar_path()
    test_rule_has_todo_write_triggers()
    test_rule_has_backlog_read_triggers()
    test_skill_has_my_todo_section()
    test_skill_has_backlog_read_routine()
    test_skill_resume_routine_reads_sidecar()
    print("\nAll 6 three-layer integration structural tests passed.")
