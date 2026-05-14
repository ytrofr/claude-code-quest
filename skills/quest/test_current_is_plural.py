#!/usr/bin/env python3
"""Regression test: I1 "Current is plural" invariant.

Rule (from ~/.claude/rules/projects/quest-dashboard.md):
  "Current" is plural — no uniqueness constraint. Never auto-lock when
  another is current.

This test exists because the bug recurred multiple times:
  - cmd_update auto-demoted peer currents when promoting one to current
  - cmd_add auto-locked new quests if any current existed
Both violate I1. Operator-explicit demotion ONLY.

Run: python3 ~/.claude/skills/quest/test_current_is_plural.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).parent / "quest.py"


def run_quest(env_data_dir, *args):
    """Run quest.py against a sandboxed HOME so we never touch real quests.json."""
    env = os.environ.copy()
    env["HOME"] = str(env_data_dir)
    # quest.py uses ROOT = Path.home() / ".claude" — so we mock $HOME
    cmd = ["python3", str(SCRIPT), *args]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)


def setup_sandbox(tmp):
    """Create $HOME/.claude/quest/data layout + symlink skills dir."""
    root = Path(tmp)
    claude = root / ".claude"
    (claude / "quest" / "data").mkdir(parents=True)
    (claude / "quest" / "run").mkdir(parents=True)
    (claude / "quest" / "site").mkdir(parents=True)
    (claude / "skills").mkdir(parents=True)
    # Symlink real skill dir so render.py/themes/quest.py are reachable
    (claude / "skills" / "quest").symlink_to(Path(__file__).parent)
    # Seed config
    (claude / "quest" / "config.json").write_text('{"dashboard_url": "http://localhost:8770"}')
    return root


def load_quests(home, project_id="testproj"):
    return json.loads((home / ".claude" / "quest" / "data" / "quests.json").read_text())["projects"][project_id]["quests"]


def assert_status(quests, qid, want):
    q = next((x for x in quests if x["id"] == qid), None)
    assert q is not None, f"quest {qid!r} missing"
    assert q["status"] == want, f"quest {qid!r}: want status={want!r}, got {q['status']!r}"


def test_update_status_current_does_not_demote_peers():
    """Promoting one quest to current MUST NOT touch other currents."""
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        # Init project + add 3 quests
        run_quest(home, "init", "testproj", "--theme", "pokemon").check_returncode()
        run_quest(home, "add", "testproj", "Alpha").check_returncode()
        run_quest(home, "add", "testproj", "Beta").check_returncode()
        run_quest(home, "add", "testproj", "Gamma").check_returncode()
        # All 3 should be current (per cmd_add fix)
        quests = load_quests(home)
        assert_status(quests, "alpha", "current")
        assert_status(quests, "beta", "current")
        assert_status(quests, "gamma", "current")
        # Promote alpha to current explicitly — MUST NOT demote beta/gamma
        run_quest(home, "update", "testproj", "alpha", "--status", "current").check_returncode()
        quests = load_quests(home)
        assert_status(quests, "alpha", "current")
        assert_status(quests, "beta", "current")
        assert_status(quests, "gamma", "current")
        print("PASS: update --status current does not demote peers")


def test_add_does_not_auto_lock_when_currents_exist():
    """Adding a new quest MUST default to current even if other currents exist."""
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run_quest(home, "init", "testproj", "--theme", "pokemon").check_returncode()
        run_quest(home, "add", "testproj", "First").check_returncode()
        run_quest(home, "add", "testproj", "Second").check_returncode()
        quests = load_quests(home)
        assert_status(quests, "first", "current")
        assert_status(quests, "second", "current")
        print("PASS: cmd_add does not auto-lock when other currents exist")


def test_add_locked_flag_still_respected():
    """Operator-explicit --locked still gates the new quest."""
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run_quest(home, "init", "testproj", "--theme", "pokemon").check_returncode()
        run_quest(home, "add", "testproj", "Backlog", "--locked").check_returncode()
        quests = load_quests(home)
        assert_status(quests, "backlog", "locked")
        print("PASS: --locked flag still respected (operator-explicit gate)")


def test_explicit_lock_via_update_still_works():
    """Operator-explicit `update --status locked <id>` MUST still demote that one quest."""
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run_quest(home, "init", "testproj", "--theme", "pokemon").check_returncode()
        run_quest(home, "add", "testproj", "Active").check_returncode()
        run_quest(home, "add", "testproj", "ToLock").check_returncode()
        run_quest(home, "update", "testproj", "tolock", "--status", "locked").check_returncode()
        quests = load_quests(home)
        assert_status(quests, "active", "current")
        assert_status(quests, "tolock", "locked")
        print("PASS: explicit `update --status locked` works on the targeted quest only")


AUTOSYNC = Path(__file__).parent / "autosync.py"


def write_plan(home, project_id, name, content_extra=""):
    """Write a minimal plan file with BLUF Project: <id> + return its path."""
    plans = home / ".claude" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    path = plans / f"{name}.md"
    path.write_text(
        f"# Plan: {name}\n"
        f"> **Plan file**: {path}\n"
        f"> **Project**: {project_id}\n\n"
        f"## BLUF\n"
        f"**Problem**: testing\n"
        f"**Solution**: testing\n\n"
        f"{content_extra}\n"
    )
    return path


def run_autosync(home, plan_path):
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        ["python3", str(AUTOSYNC), str(plan_path)],
        env=env, capture_output=True, text=True, check=False,
    )


def test_autosync_does_not_auto_lock_when_currents_exist():
    """autosync hook fires on plan writes WITHOUT operator command.
    It MUST default new quests to current and MUST NOT touch peer currents."""
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run_quest(home, "init", "testproj", "--theme", "pokemon").check_returncode()
        # Seed 2 currents via CLI
        run_quest(home, "add", "testproj", "PeerOne").check_returncode()
        run_quest(home, "add", "testproj", "PeerTwo").check_returncode()
        # Fire autosync with a new plan referencing testproj
        plan_path = write_plan(home, "testproj", "autosync-quest")
        result = run_autosync(home, plan_path)
        assert result.returncode == 0, f"autosync failed: stderr={result.stderr}"
        quests = load_quests(home)
        # Peer currents MUST survive
        assert_status(quests, "peerone", "current")
        assert_status(quests, "peertwo", "current")
        # New quest from autosync MUST be current (not locked)
        new = [q for q in quests if q.get("plan") == plan_path.name]
        assert len(new) == 1, f"autosync did not add quest: quests={quests}"
        assert new[0]["status"] == "current", (
            f"autosync auto-locked the new quest: {new[0]['status']!r} (should be 'current')"
        )
        print("PASS: autosync defaults new quest to current; peers untouched")


def test_autosync_update_does_not_mutate_peer_status():
    """When autosync re-fires on an existing plan, peer quest statuses MUST NOT change."""
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run_quest(home, "init", "testproj", "--theme", "pokemon").check_returncode()
        run_quest(home, "add", "testproj", "Alpha").check_returncode()
        plan_path = write_plan(home, "testproj", "second-quest")
        run_autosync(home, plan_path).check_returncode()
        # Now demote alpha explicitly
        run_quest(home, "update", "testproj", "alpha", "--status", "locked").check_returncode()
        # Re-fire autosync on the same plan (update path)
        run_autosync(home, plan_path).check_returncode()
        quests = load_quests(home)
        # Alpha must STILL be locked — autosync update path must not flip it
        assert_status(quests, "alpha", "locked")
        # New quest must still be current
        assert_status(quests, "second-quest", "current")
        print("PASS: autosync update path does not mutate peer quest status")


def test_done_auto_promote_only_when_no_currents():
    """cmd_done auto-promotes a locked → current ONLY when zero currents remain.
    This is the documented safe behavior — but we lock it in to prevent drift."""
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run_quest(home, "init", "testproj", "--theme", "pokemon").check_returncode()
        run_quest(home, "add", "testproj", "Active").check_returncode()
        run_quest(home, "add", "testproj", "Backlog").check_returncode()
        run_quest(home, "update", "testproj", "backlog", "--status", "locked").check_returncode()
        # Done active → no currents left → backlog should promote
        run_quest(home, "done", "testproj", "active").check_returncode()
        quests = load_quests(home)
        assert_status(quests, "active", "done")
        assert_status(quests, "backlog", "current")
        print("PASS: cmd_done auto-promotes locked only when zero currents")


def test_done_does_not_promote_when_currents_remain():
    """If other currents exist, marking one done MUST NOT promote a locked quest."""
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run_quest(home, "init", "testproj", "--theme", "pokemon").check_returncode()
        run_quest(home, "add", "testproj", "OneActive").check_returncode()
        run_quest(home, "add", "testproj", "TwoActive").check_returncode()
        run_quest(home, "add", "testproj", "ThreeBacklog").check_returncode()
        run_quest(home, "update", "testproj", "threebacklog", "--status", "locked").check_returncode()
        run_quest(home, "done", "testproj", "oneactive").check_returncode()
        quests = load_quests(home)
        assert_status(quests, "oneactive", "done")
        assert_status(quests, "twoactive", "current")
        # Critical: backlog stays locked because twoactive is still current
        assert_status(quests, "threebacklog", "locked")
        print("PASS: cmd_done does NOT promote locked when peer currents exist")


if __name__ == "__main__":
    test_update_status_current_does_not_demote_peers()
    test_add_does_not_auto_lock_when_currents_exist()
    test_add_locked_flag_still_respected()
    test_explicit_lock_via_update_still_works()
    test_autosync_does_not_auto_lock_when_currents_exist()
    test_autosync_update_does_not_mutate_peer_status()
    test_done_auto_promote_only_when_no_currents()
    test_done_does_not_promote_when_currents_remain()
    print("\nAll 8 I1 'Current is plural' regression tests passed.")
