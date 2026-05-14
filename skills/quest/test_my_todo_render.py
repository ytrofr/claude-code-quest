#!/usr/bin/env python3
"""Tests: render-layer pure functions for the My To-Do section.

Spec: ~/.claude/skills/quest/docs/specs/2026-05-14-quest-my-todo-design.md §5

  render_notes_html(notes)  -> HTML-escaped notes, <br> on single newline,
                               <p> per blank-line-separated paragraph
  my_todo_scope(parsed)     -> render scope keys from a parse_sidecar() result:
                               {my_todo, my_todo_done, my_todo_total,
                                my_todo_next, my_notes_html, my_todo_has}

Both pure — render.py just glues read-file -> parse_sidecar -> my_todo_scope.

Run: python3 ~/.claude/skills/quest/test_my_todo_render.py
"""
from sidecar import my_todo_scope, parse_sidecar, render_notes_html


def test_notes_html_empty():
    assert render_notes_html("") == "", render_notes_html("")
    print("PASS: render_notes_html('') → ''")


def test_notes_html_single_paragraph():
    assert render_notes_html("hello world") == "<p>hello world</p>", render_notes_html("hello world")
    print("PASS: render_notes_html wraps a single line in <p>")


def test_notes_html_single_newline_is_br():
    assert render_notes_html("line one\nline two") == "<p>line one<br>line two</p>"
    print("PASS: single newline → <br>")


def test_notes_html_blank_line_splits_paragraphs():
    assert render_notes_html("para one\n\npara two") == "<p>para one</p><p>para two</p>"
    print("PASS: blank line → separate <p> paragraphs")


def test_notes_html_escapes_markup():
    out = render_notes_html("<script>alert(1)</script>")
    assert "<script>" not in out, out
    assert "&lt;script&gt;" in out, out
    print("PASS: render_notes_html escapes HTML markup (untrusted input)")


def test_notes_html_escapes_ampersand():
    assert render_notes_html("a & b") == "<p>a &amp; b</p>", render_notes_html("a & b")
    print("PASS: render_notes_html escapes ampersand")


def test_scope_empty_parsed():
    s = my_todo_scope(parse_sidecar(""))
    assert s["my_todo_has"] is False, s
    assert s["my_todo"] == [], s
    assert s["my_todo_total"] == 0 and s["my_todo_done"] == 0, s
    assert s["my_notes_html"] == "", s
    print("PASS: my_todo_scope on empty parse → my_todo_has False, empty scope")


def test_scope_counts_and_done_class():
    s = my_todo_scope(parse_sidecar("- [ ] a\n- [x] b\n- [ ] c"))
    assert s["my_todo_total"] == 3 and s["my_todo_done"] == 1, s
    assert s["my_todo_has"] is True, s
    classes = [t["done_class"] for t in s["my_todo"]]
    assert classes == ["todo", "done", "todo"], classes
    # done item carries a visible mark; todo item does not
    assert s["my_todo"][1]["done_mark"] and not s["my_todo"][0]["done_mark"], s["my_todo"]
    print("PASS: my_todo_scope sets counts + done_class + done_mark")


def test_scope_next_is_first_undone():
    s = my_todo_scope(parse_sidecar("- [x] already done\n- [ ] do this next\n- [ ] later"))
    assert s["my_todo_next"] == "do this next", s["my_todo_next"]
    print("PASS: my_todo_next is the first not-done title")


def test_scope_next_truncated():
    long_title = "x" * 200
    s = my_todo_scope(parse_sidecar(f"- [ ] {long_title}"))
    assert len(s["my_todo_next"]) <= 81, len(s["my_todo_next"])  # 80 + ellipsis
    assert s["my_todo_next"].endswith("…"), s["my_todo_next"]
    print("PASS: my_todo_next truncates a long title with an ellipsis")


def test_scope_notes_rendered_html():
    s = my_todo_scope(parse_sidecar("## Notes\nsoak ends Friday"))
    assert s["my_notes_html"] == "<p>soak ends Friday</p>", s["my_notes_html"]
    assert s["my_notes"] == "soak ends Friday", s["my_notes"]  # raw — for plain-text briefing
    assert s["my_todo_has"] is True, s
    print("PASS: my_todo_scope renders notes to HTML + keeps raw my_notes")


if __name__ == "__main__":
    test_notes_html_empty()
    test_notes_html_single_paragraph()
    test_notes_html_single_newline_is_br()
    test_notes_html_blank_line_splits_paragraphs()
    test_notes_html_escapes_markup()
    test_notes_html_escapes_ampersand()
    test_scope_empty_parsed()
    test_scope_counts_and_done_class()
    test_scope_next_is_first_undone()
    test_scope_next_truncated()
    test_scope_notes_rendered_html()
    print("\nAll 11 render-layer (render_notes_html + my_todo_scope) tests passed.")
