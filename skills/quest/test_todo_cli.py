#!/usr/bin/env python3
"""Tests: /quest todo CLI + the sidecar file-edit helpers.

Spec: ~/.claude/skills/quest/docs/specs/2026-05-14-quest-my-todo-design.md §4

Two layers:
  - pure str->str helpers in sidecar.py (ensure_header / append_todo /
    set_todo_done / remove_todo / append_note / sidecar_path) — tested directly
  - the `quest.py todo <action> ...` subcommand — tested via subprocess against
    a sandboxed $HOME (same pattern as test_current_is_plural.py)

Run: python3 ~/.claude/skills/quest/test_todo_cli.py
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

from sidecar import (
    append_note,
    append_todo,
    ensure_header,
    remove_todo,
    set_todo_done,
    sidecar_path,
)

SCRIPT = Path(__file__).parent / "quest.py"


# ---- sandbox helpers (mirrors test_current_is_plural.py) ----

def setup_sandbox(tmp):
    root = Path(tmp)
    claude = root / ".claude"
    (claude / "quest" / "data").mkdir(parents=True)
    (claude / "quest" / "run").mkdir(parents=True)
    (claude / "quest" / "site").mkdir(parents=True)
    (claude / "skills").mkdir(parents=True)
    (claude / "skills" / "quest").symlink_to(Path(__file__).parent)
    (claude / "quest" / "config.json").write_text('{"dashboard_url": "http://localhost:8770"}')
    return root


def run_quest(home, *args):
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        ["python3", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False
    )


def notes_file(home, pid, qid):
    return home / ".claude" / "quest" / "data" / "notes" / f"{pid}__{qid}.md"


# ---- pure helper tests ----

def test_sidecar_path_shape():
    p = sidecar_path("apollo", "build-login")
    assert str(p).endswith("quest/data/notes/apollo__build-login.md"), p
    print("PASS: sidecar_path returns <...>/notes/<proj>__<quest>.md")


def test_ensure_header_adds_when_missing():
    out = ensure_header("- [ ] task", "Anchor Town")
    assert out.startswith("# My To-Do — Anchor Town\n"), repr(out)
    assert "- [ ] task" in out, repr(out)
    print("PASS: ensure_header prepends header when missing")


def test_ensure_header_idempotent():
    text = "# My To-Do — Anchor Town\n\n- [ ] task"
    assert ensure_header(text, "Anchor Town") == text, "should be unchanged"
    print("PASS: ensure_header is idempotent when header present")


def test_append_todo_after_last_checkbox():
    text = "# My To-Do — X\n\n- [ ] one\n- [ ] two\n"
    out = append_todo(text, "three")
    lines = [l for l in out.splitlines() if l.startswith("- [")]
    assert lines == ["- [ ] one", "- [ ] two", "- [ ] three"], lines
    print("PASS: append_todo inserts after the last checkbox line")


def test_append_todo_on_header_only():
    out = append_todo("# My To-Do — X\n", "first task")
    assert "- [ ] first task" in out, repr(out)
    print("PASS: append_todo works on header-only text")


def test_append_todo_preserves_freeform_content():
    text = "# My To-Do — X\n\n- [ ] one\nloose note line\n- [ ] two\n"
    out = append_todo(text, "three")
    assert "loose note line" in out, repr(out)
    assert out.index("- [ ] two") < out.index("- [ ] three"), repr(out)
    print("PASS: append_todo preserves free-form content between checkboxes")


def test_set_todo_done_flips_nth():
    text = "- [ ] one\n- [ ] two\n- [ ] three"
    out = set_todo_done(text, 2, True)
    assert out.splitlines() == ["- [ ] one", "- [x] two", "- [ ] three"], out
    print("PASS: set_todo_done flips the Nth checkbox to done")


def test_set_todo_done_unflips():
    out = set_todo_done("- [x] one\n- [x] two", 1, False)
    assert out.splitlines() == ["- [ ] one", "- [x] two"], out
    print("PASS: set_todo_done with done=False flips back to undone")


def test_set_todo_done_out_of_range_raises():
    try:
        set_todo_done("- [ ] only one", 5, True)
    except IndexError:
        print("PASS: set_todo_done raises IndexError on out-of-range n")
        return
    raise AssertionError("expected IndexError for out-of-range n")


def test_remove_todo_deletes_nth():
    text = "- [ ] one\n- [ ] two\n- [ ] three"
    out = remove_todo(text, 2)
    assert [l for l in out.splitlines() if l.startswith("- [")] == [
        "- [ ] one",
        "- [ ] three",
    ], out
    print("PASS: remove_todo deletes the Nth checkbox line")


def test_remove_todo_out_of_range_raises():
    try:
        remove_todo("- [ ] only one", 9)
    except IndexError:
        print("PASS: remove_todo raises IndexError on out-of-range n")
        return
    raise AssertionError("expected IndexError for out-of-range n")


def test_append_note_creates_section():
    out = append_note("# My To-Do — X\n\n- [ ] task", "soak ends Friday")
    assert "## Notes" in out, repr(out)
    assert "soak ends Friday" in out, repr(out)
    assert out.index("## Notes") < out.index("soak ends Friday"), repr(out)
    print("PASS: append_note creates a ## Notes section when absent")


def test_append_note_appends_to_existing_section():
    text = "# My To-Do — X\n\n## Notes\n\nfirst note"
    out = append_note(text, "second note")
    assert out.count("## Notes") == 1, "must not duplicate the heading"
    assert "first note" in out and "second note" in out, repr(out)
    assert out.index("first note") < out.index("second note"), repr(out)
    print("PASS: append_note appends under an existing ## Notes section")


# ---- subprocess CLI tests ----

def test_cli_add_creates_sidecar():
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run_quest(home, "init", "testproj", "--theme", "pokemon").check_returncode()
        run_quest(home, "add", "testproj", "Anchor Town").check_returncode()
        r = run_quest(home, "todo", "add", "testproj", "anchor-town", "ask Yannai about the key")
        assert r.returncode == 0, f"stderr={r.stderr}"
        f = notes_file(home, "testproj", "anchor-town")
        assert f.exists(), "sidecar file not created"
        body = f.read_text()
        assert body.startswith("# My To-Do — Anchor Town"), repr(body)
        assert "- [ ] ask Yannai about the key" in body, repr(body)
        print("PASS: `todo add` creates the sidecar with header + todo")


def test_cli_add_rejects_unknown_quest():
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run_quest(home, "init", "testproj", "--theme", "pokemon").check_returncode()
        r = run_quest(home, "todo", "add", "testproj", "no-such-quest", "ghost task")
        assert r.returncode != 0, "should reject unknown quest"
        assert not notes_file(home, "testproj", "no-such-quest").exists(), (
            "must not create a sidecar for a nonexistent quest"
        )
        print("PASS: `todo add` rejects an unknown quest, creates no file")


def test_cli_done_flips_checkbox_in_file():
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run_quest(home, "init", "testproj", "--theme", "pokemon").check_returncode()
        run_quest(home, "add", "testproj", "Anchor Town").check_returncode()
        run_quest(home, "todo", "add", "testproj", "anchor-town", "first").check_returncode()
        run_quest(home, "todo", "add", "testproj", "anchor-town", "second").check_returncode()
        r = run_quest(home, "todo", "done", "testproj", "anchor-town", "1")
        assert r.returncode == 0, f"stderr={r.stderr}"
        body = notes_file(home, "testproj", "anchor-town").read_text()
        assert "- [x] first" in body, repr(body)
        assert "- [ ] second" in body, repr(body)
        print("PASS: `todo done 1` flips the first checkbox in the file")


def test_cli_done_out_of_range_errors():
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run_quest(home, "init", "testproj", "--theme", "pokemon").check_returncode()
        run_quest(home, "add", "testproj", "Anchor Town").check_returncode()
        run_quest(home, "todo", "add", "testproj", "anchor-town", "only one").check_returncode()
        r = run_quest(home, "todo", "done", "testproj", "anchor-town", "99")
        assert r.returncode != 0, "out-of-range index should error"
        print("PASS: `todo done 99` (out of range) exits nonzero")


def test_cli_list_prints_path_and_content():
    with tempfile.TemporaryDirectory() as tmp:
        home = setup_sandbox(tmp)
        run_quest(home, "init", "testproj", "--theme", "pokemon").check_returncode()
        run_quest(home, "add", "testproj", "Anchor Town").check_returncode()
        run_quest(home, "todo", "add", "testproj", "anchor-town", "visible task").check_returncode()
        r = run_quest(home, "todo", "list", "testproj", "anchor-town")
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert "visible task" in r.stdout, r.stdout
        assert "testproj__anchor-town.md" in r.stdout, r.stdout
        print("PASS: `todo list` prints the file path and content")


if __name__ == "__main__":
    test_sidecar_path_shape()
    test_ensure_header_adds_when_missing()
    test_ensure_header_idempotent()
    test_append_todo_after_last_checkbox()
    test_append_todo_on_header_only()
    test_append_todo_preserves_freeform_content()
    test_set_todo_done_flips_nth()
    test_set_todo_done_unflips()
    test_set_todo_done_out_of_range_raises()
    test_remove_todo_deletes_nth()
    test_remove_todo_out_of_range_raises()
    test_append_note_creates_section()
    test_append_note_appends_to_existing_section()
    test_cli_add_creates_sidecar()
    test_cli_add_rejects_unknown_quest()
    test_cli_done_flips_checkbox_in_file()
    test_cli_done_out_of_range_errors()
    test_cli_list_prints_path_and_content()
    print("\nAll 18 /quest todo CLI + sidecar-helper tests passed.")
