#!/usr/bin/env python3
"""Unit tests: parse_sidecar() — the My To-Do sidecar markdown parser.

Spec: ~/.claude/skills/quest/docs/specs/2026-05-14-quest-my-todo-design.md §3.3

parse_sidecar(text) -> {
    "todos": [{"title": str, "done": bool}, ...],   # file order
    "notes": str,                                    # raw text under "## Notes"
    "has_content": bool,                             # todos non-empty OR notes non-empty
}

Pure function — no I/O, deterministic. HTML escaping is a SEPARATE concern
(render layer), so the parser returns raw title/notes text verbatim.

Run: python3 ~/.claude/skills/quest/test_my_todo_parser.py
"""
from sidecar import parse_sidecar


def test_empty_string():
    r = parse_sidecar("")
    assert r["todos"] == [], r
    assert r["notes"] == "", r
    assert r["has_content"] is False, r
    print("PASS: empty string → empty result, has_content False")


def test_single_unchecked_todo():
    r = parse_sidecar("- [ ] feed the cat")
    assert r["todos"] == [{"title": "feed the cat", "done": False}], r
    assert r["has_content"] is True, r
    print("PASS: single unchecked todo parsed, has_content True")


def test_checked_lower_and_upper_x():
    r = parse_sidecar("- [x] done one\n- [X] done two")
    assert r["todos"] == [
        {"title": "done one", "done": True},
        {"title": "done two", "done": True},
    ], r
    print("PASS: [x] and [X] both parse as done")


def test_multiple_order_and_mixed_state():
    text = "- [ ] first\n- [x] second\n- [ ] third"
    r = parse_sidecar(text)
    assert [t["title"] for t in r["todos"]] == ["first", "second", "third"], r
    assert [t["done"] for t in r["todos"]] == [False, True, False], r
    print("PASS: multiple todos keep file order with mixed done state")


def test_notes_section_captured():
    text = "- [ ] a task\n\n## Notes\n\nremember the soak window ends Friday"
    r = parse_sidecar(text)
    assert r["todos"] == [{"title": "a task", "done": False}], r
    assert r["notes"] == "remember the soak window ends Friday", r
    print("PASS: ## Notes section captured as raw text")


def test_notes_heading_case_insensitive():
    for heading in ("## Notes", "## notes", "## NOTES", "##   Notes"):
        r = parse_sidecar(f"{heading}\nbody line")
        assert r["notes"] == "body line", (heading, r)
    print("PASS: ## Notes heading is case-insensitive")


def test_notes_stop_at_next_heading():
    text = "## Notes\nkeep this\n## Other\ndrop this"
    r = parse_sidecar(text)
    assert r["notes"] == "keep this", r
    print("PASS: notes capture stops at the next ## heading")


def test_title_header_line_ignored():
    text = "# My To-Do — Anchor Town\n\n- [ ] real task"
    r = parse_sidecar(text)
    assert r["todos"] == [{"title": "real task", "done": False}], r
    assert r["notes"] == "", r
    print("PASS: '# ' title header line is ignored")


def test_prose_outside_notes_ignored():
    text = "just some loose prose\n- [ ] the task\nmore loose prose"
    r = parse_sidecar(text)
    assert r["todos"] == [{"title": "the task", "done": False}], r
    assert r["notes"] == "", r
    print("PASS: non-checkbox prose outside Notes is ignored")


def test_malformed_empty_brackets_ignored():
    text = "- [] not a todo\n- [ ] real todo"
    r = parse_sidecar(text)
    assert r["todos"] == [{"title": "real todo", "done": False}], r
    print("PASS: malformed '- [] ' (empty brackets) is ignored")


def test_title_whitespace_stripped():
    r = parse_sidecar("- [ ]    padded title   ")
    assert r["todos"] == [{"title": "padded title", "done": False}], r
    print("PASS: leading/trailing whitespace stripped from title")


def test_whitespace_only_title_dropped():
    r = parse_sidecar("- [ ]      \n- [ ] real")
    assert r["todos"] == [{"title": "real", "done": False}], r
    print("PASS: whitespace-only title is dropped, not a todo")


def test_hebrew_unicode_title_preserved():
    r = parse_sidecar("- [ ] לשאול את יניב על מפתח ה-API")
    assert r["todos"] == [
        {"title": "לשאול את יניב על מפתח ה-API", "done": False}
    ], r
    print("PASS: Hebrew/unicode title preserved verbatim")


def test_notes_only_file_has_content():
    r = parse_sidecar("## Notes\nthis file has only notes, no todos")
    assert r["todos"] == [], r
    assert r["notes"] == "this file has only notes, no todos", r
    assert r["has_content"] is True, r
    print("PASS: notes-only file → has_content True")


if __name__ == "__main__":
    test_empty_string()
    test_single_unchecked_todo()
    test_checked_lower_and_upper_x()
    test_multiple_order_and_mixed_state()
    test_notes_section_captured()
    test_notes_heading_case_insensitive()
    test_notes_stop_at_next_heading()
    test_title_header_line_ignored()
    test_prose_outside_notes_ignored()
    test_malformed_empty_brackets_ignored()
    test_title_whitespace_stripped()
    test_whitespace_only_title_dropped()
    test_hebrew_unicode_title_preserved()
    test_notes_only_file_has_content()
    print("\nAll 14 parse_sidecar() tests passed.")
