#!/usr/bin/env python3
"""Sidecar file support for the quest "My To-Do" feature.

A per-quest markdown sidecar at ~/.claude/quest/data/notes/<proj>__<quest>.md
holds user-authored todos + free-form notes. autosync never touches this file —
it is autosync-immune by construction (autosync only reads plan files).

Spec: ~/.claude/skills/quest/docs/specs/2026-05-14-quest-my-todo-design.md §3

parse_sidecar() is a pure function — no I/O, deterministic. HTML escaping is a
separate concern handled at the render layer, so the parser returns raw text.
"""
import html as _html
import re
from pathlib import Path

# A todo line: optional indent, "-", "[", exactly one of space/x/X, "]", title.
# "- [] foo" (empty brackets) does NOT match — the class requires one char.
_TODO_RE = re.compile(r"^\s*-\s*\[([ xX])\]\s*(.+?)\s*$")
# A level-2 heading: line starting with "## " (not "# ", not "###").
_H2_RE = re.compile(r"^##\s")
# The Notes heading specifically — case-insensitive, tolerant of extra spaces.
_NOTES_H2_RE = re.compile(r"^##\s+notes\s*$", re.IGNORECASE)
# The checkbox marker inside a todo line — used to flip done state in place.
_CHECKBOX_SUB_RE = re.compile(r"\[[ xX]\]")


def sidecar_path(project_id: str, quest_id: str) -> Path:
    """Absolute path to a quest's My To-Do sidecar file.

    ~/.claude/quest/data/notes/<project_id>__<quest_id>.md — both ids are
    kebab-safe slugs, so "__" is a collision-proof separator.
    """
    return (
        Path.home() / ".claude" / "quest" / "data" / "notes"
        / f"{project_id}__{quest_id}.md"
    )


def ensure_header(text: str, quest_name: str) -> str:
    """Prepend "# My To-Do — <quest_name>" if the text has no "# " header.

    Idempotent: text that already starts with a "# " line is returned as-is.
    """
    if text.lstrip().startswith("# "):
        return text
    return f"# My To-Do — {quest_name}\n\n{text}"


def append_todo(text: str, title: str) -> str:
    """Insert "- [ ] <title>" after the last checkbox line.

    If the text has no checkbox lines, append at the end. Free-form content
    between checkboxes is preserved — this is a targeted insert, not a rewrite.
    """
    new_line = f"- [ ] {title}"
    lines = text.splitlines()
    last_cb = -1
    for i, line in enumerate(lines):
        if _TODO_RE.match(line):
            last_cb = i
    if last_cb >= 0:
        lines.insert(last_cb + 1, new_line)
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(new_line)
    return "\n".join(lines) + "\n"


def set_todo_done(text: str, n: int, done: bool) -> str:
    """Flip the Nth (1-based) checkbox line's done state. Raises IndexError
    when n is out of range."""
    lines = text.splitlines()
    mark = "x" if done else " "
    count = 0
    for i, line in enumerate(lines):
        if _TODO_RE.match(line):
            count += 1
            if count == n:
                lines[i] = _CHECKBOX_SUB_RE.sub(f"[{mark}]", line, count=1)
                return "\n".join(lines)
    raise IndexError(f"todo index {n} out of range (have {count})")


def remove_todo(text: str, n: int) -> str:
    """Delete the Nth (1-based) checkbox line. Raises IndexError when n is
    out of range."""
    lines = text.splitlines()
    count = 0
    for i, line in enumerate(lines):
        if _TODO_RE.match(line):
            count += 1
            if count == n:
                del lines[i]
                return "\n".join(lines)
    raise IndexError(f"todo index {n} out of range (have {count})")


def append_note(text: str, note: str) -> str:
    """Append a line to the "## Notes" section, creating the section if absent."""
    lines = text.splitlines()
    notes_idx = -1
    for i, line in enumerate(lines):
        if _NOTES_H2_RE.match(line.strip()):
            notes_idx = i
            break
    if notes_idx < 0:
        body = text.rstrip("\n")
        if body:
            body += "\n\n"
        return f"{body}## Notes\n\n{note}\n"
    # Find the end of the notes section (next "## " heading or EOF), then
    # insert before any trailing blank lines inside the section.
    end = len(lines)
    for j in range(notes_idx + 1, len(lines)):
        if _H2_RE.match(lines[j]):
            end = j
            break
    insert_at = end
    while insert_at > notes_idx + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, note)
    return "\n".join(lines)


def parse_sidecar(text: str) -> dict:
    """Parse sidecar markdown into {todos, notes, has_content}.

    todos: [{"title": str, "done": bool}] in file order. A checkbox line whose
           title is empty/whitespace-only is dropped.
    notes: raw text under a "## Notes" heading (until EOF or the next "## "
           heading), stripped. "" when absent.
    has_content: True if there is at least one todo OR any notes text.
    """
    todos: list[dict] = []
    notes_lines: list[str] = []
    in_notes = False

    for line in text.splitlines():
        if _H2_RE.match(line):
            # Any "## " heading toggles notes mode: on for "## Notes", off
            # for any other level-2 heading.
            in_notes = bool(_NOTES_H2_RE.match(line.strip()))
            continue
        if in_notes:
            notes_lines.append(line)
            continue
        m = _TODO_RE.match(line)
        if m:
            title = m.group(2).strip()
            if title:
                todos.append({"title": title, "done": m.group(1) in ("x", "X")})

    notes = "\n".join(notes_lines).strip()
    return {"todos": todos, "notes": notes, "has_content": bool(todos or notes)}


# Inline markdown patterns. Applied AFTER HTML escaping so the raw markdown
# delimiters (`** * `) work on escaped content. Order matters: code first
# (so its contents aren't reinterpreted), then bold, then italic.
_MD_CODE = re.compile(r"`([^`\n]+)`")
_MD_BOLD = re.compile(r"\*\*([^*\n]+?)\*\*")
_MD_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")


def render_inline_md(text: str) -> str:
    """Render a SINGLE line of inline markdown to safe HTML.

    Supports: **bold**, *italic*, `code`. Everything else is HTML-escaped.
    Used by task titles + line-level renders. Multi-line input is handled
    by callers (split on \\n first).
    """
    if not text:
        return ""
    out = _html.escape(text)
    # Inline code FIRST so its contents are not reinterpreted as bold/italic
    out = _MD_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = _MD_BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", out)
    out = _MD_ITALIC.sub(lambda m: f"<em>{m.group(1)}</em>", out)
    return out


def render_notes_html(notes: str) -> str:
    """Render raw notes text to safe HTML: HTML-escape, then apply inline
    markdown (** * `), single newline -> <br>, blank-line-separated blocks
    -> separate <p> paragraphs.
    """
    notes = notes.strip()
    if not notes:
        return ""
    out = []
    for para in re.split(r"\n\s*\n", notes):
        para = para.strip()
        if not para:
            continue
        # Render inline markdown per-line so <br> stays between lines
        rendered_lines = [render_inline_md(line) for line in para.split("\n")]
        out.append(f"<p>{'<br>'.join(rendered_lines)}</p>")
    return "".join(out)


def my_todo_scope(parsed: dict) -> dict:
    """Build the render scope keys for the My To-Do section from a
    parse_sidecar() result.

    Returns: my_todo (list of {title, done, done_class, done_mark}),
    my_todo_done, my_todo_total, my_todo_next (first not-done title, truncated
    to 80 chars + ellipsis), my_notes_html, my_todo_has.
    """
    todos = []
    done_count = 0
    next_title = ""
    for t in parsed["todos"]:
        done = t["done"]
        if done:
            done_count += 1
        elif not next_title:
            next_title = t["title"]
        todos.append({
            "title": t["title"],
            "title_html": render_inline_md(t["title"]),
            "done": done,
            "done_class": "done" if done else "todo",
            "done_mark": "✓" if done else "",
        })
    if len(next_title) > 80:
        next_title = next_title[:80] + "…"
    next_title_html = render_inline_md(next_title)
    return {
        "my_todo": todos,
        "my_todo_done": done_count,
        "my_todo_total": len(todos),
        "my_todo_next": next_title,                        # raw — for plain-text briefing
        "my_todo_next_html": next_title_html,              # markdown-rendered for HTML preview
        "my_notes": parsed["notes"],                       # raw — for plain-text briefing
        "my_notes_html": render_notes_html(parsed["notes"]),
        "my_todo_has": parsed["has_content"],
    }
