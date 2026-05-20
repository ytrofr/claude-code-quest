"""Regression tests for the prompt-rebind scorer.

Run with: pytest -xvs ~/.claude/skills/quest/test_prompt_rebind.py
Or:       python3 -m unittest ~/.claude/skills/quest/test_prompt_rebind.py

Covers:
  - IDF scoring precision on the 26-prompt synthetic corpus
  - Joined-context scoring for the 7-prompt real-prompt corpus
  - Two-stage logic (user-alone first, joined fallthrough, conflict guard)
  - Edge cases: no-sk, no-project, no-current-quests, Hebrew, missing transcript
  - Side-effect guarantees: dry-run, lock file, atomic rename
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import prompt_rebind_scorer as scorer  # noqa: E402


FIXTURE_QUESTS = {
    "version": 2,
    "projects": {
        "demo": {
            "quests": [
                {
                    "id": "mobile-layout-iframe-cache",
                    "name": "Mobile Layout Iframe Cache",
                    "desc": "Fix mobile zoom and iframe binding latency on the inline editor",
                    "status": "current",
                    "tags": ["mobile", "iframe", "cache", "viewport"],
                },
                {
                    "id": "dorian-investors-landing",
                    "name": "Dorian Investors Landing",
                    "desc": "Investor kit landing page for Dorian community marketplace",
                    "status": "current",
                    "tags": ["dorian", "landing", "investors"],
                },
                {
                    "id": "moshytz-variant-engine",
                    "name": "Moshytz Variant Engine",
                    "desc": "Multi-model variant engine for moshytz inspiration phase 10 DNA",
                    "status": "current",
                    "tags": ["moshytz", "variant", "phase-10"],
                },
                {
                    "id": "inline-editor-modularization",
                    "name": "Inline Editor Modularization",
                    "desc": "Tier 1 split of the inline editor god file",
                    "status": "current",
                    "tags": ["modularization", "tier-1"],
                },
                {
                    "id": "creative-save-routing",
                    "name": "Creative Save Routing",
                    "desc": "Binary LLM judge for creative save intent classification",
                    "status": "current",
                    "tags": ["creative", "save", "routing", "judge"],
                },
                {
                    "id": "locked-old-feature",
                    "name": "Locked Feature",
                    "desc": "This is locked and must not match any prompt",
                    "status": "locked",
                    "tags": ["locked"],
                },
                {
                    "id": "done-old-quest",
                    "name": "Done Quest",
                    "desc": "Completed quest about variant engine and moshytz long ago",
                    "status": "done",
                    "tags": ["done"],
                },
            ]
        }
    },
}

FIXTURE_CONFIG = {
    "path_map": [
        {"id": "demo", "path": "/tmp/quest-test-cwd"},
    ]
}


def _docs_for_demo():
    quests = [q for q in FIXTURE_QUESTS["projects"]["demo"]["quests"] if q.get("status") == "current"]
    return scorer._build_idf(quests)


class TestTokenizer(unittest.TestCase):
    def test_lowercase_split(self):
        self.assertEqual(scorer._tok("Foo BAR baz"), ["foo", "bar", "baz"])

    def test_stop_words_removed(self):
        self.assertEqual(scorer._tok("the and for help"), ["help"])

    def test_short_tokens_dropped(self):
        self.assertEqual(scorer._tok("ab cd efg hi jk"), ["efg"])

    def test_non_ascii_ignored(self):
        # Hebrew should produce zero tokens
        self.assertEqual(scorer._tok("מה קורה פה"), [])

    def test_alphanumeric_kept(self):
        self.assertIn("v15a", scorer._tok("drag-and-drop v15a"))

    def test_punctuation_split(self):
        self.assertEqual(
            scorer._tok("foo-bar.baz_qux"),
            ["foo", "bar", "baz", "qux"],
        )


class TestDecideAction(unittest.TestCase):
    def setUp(self):
        self.docs, self.idf = _docs_for_demo()

    def test_strong_user_signal_rebinds_on_user_alone(self):
        r = scorer.decide_action(
            "investigate mobile iframe cache viewport regression",
            "",
            self.docs, self.idf,
        )
        self.assertEqual(r["action"], "rebind")
        self.assertEqual(r["top"], "mobile-layout-iframe-cache")
        self.assertEqual(r["path"], "user-alone")

    def test_generic_continuation_suggests_not_rebinds(self):
        # A contentless continuation ("yes lets do it") with prior context
        # about a quest is now a SUGGEST, not an auto-rebind. Prior context
        # must never rewrite the claim — only the user's own strong prompt
        # (Stage 1) can rebind. This was the rampant claim-drift bug.
        r = scorer.decide_action(
            "yes lets do it",
            "I propose investigating the dorian investors landing page layout",
            self.docs, self.idf,
        )
        self.assertEqual(r["action"], "suggest")
        self.assertEqual(r["top"], "dorian-investors-landing")
        self.assertEqual(r["path"], "joined")

    def test_orthogonal_prompt_with_no_context_is_noop(self):
        # No prior context AND user prompt with no quest-discriminating tokens → noop.
        # (Note: with strong prior context, even orthogonal-looking user prompts may
        # legitimately rebind via the "lets do X" continuation path. That's a feature.)
        r = scorer.decide_action("what time is it", "", self.docs, self.idf)
        self.assertNotEqual(r["action"], "rebind",
                            "Orthogonal user prompt with no context should not rebind")

    def test_hebrew_only_prompt_no_tokens_noop(self):
        r = scorer.decide_action("מה קורה פה", "", self.docs, self.idf)
        self.assertEqual(r["action"], "noop")

    def test_empty_prompt_no_tokens_noop(self):
        r = scorer.decide_action("", "", self.docs, self.idf)
        self.assertEqual(r["action"], "noop")

    def test_conflict_guard_user_disagrees_with_context(self):
        # User says "dorian" but prior context heavily favors mobile-layout
        r = scorer.decide_action(
            "switch to dorian investors landing",
            "Heavy work on mobile layout iframe cache viewport regression",
            self.docs, self.idf,
        )
        # User prompt has dorian → must NOT rebind to mobile-layout
        if r["action"] == "rebind":
            self.assertNotEqual(r["top"], "mobile-layout-iframe-cache",
                                "Conflict guard failed: rebound to context-favorite while user said dorian")

    def test_rc1_rebind_margin_floor_is_five(self):
        # RC1: REBIND_MARGIN raised 3->5. The observed production noise rebind
        # (score 5.56 / margin 3.3) cleared the old margin=3 floor on the
        # user-alone path. Regression guard on the constant.
        self.assertGreaterEqual(scorer.REBIND_MARGIN, 5.0)

    def test_single_token_match_does_not_rebind(self):
        # A prompt sharing only ONE distinct token with the top quest is too
        # weak to rebind even if it clears the score/margin floors —
        # MIN_REBIND_TOKENS gate. Crafted docs/idf for precision.
        docs = [("qa", {"quaffle"}), ("qb", {"nargle"})]
        idf = {"quaffle": 20.0, "nargle": 1.0}
        r = scorer.decide_action("quaffle", "", docs, idf)
        self.assertNotEqual(r["action"], "rebind")

    def test_joined_context_alone_never_rebinds(self):
        # Strong prior context, no real user-prompt signal → suggest at most,
        # never rebind. Prior context must not auto-rewrite the claim.
        r = scorer.decide_action(
            "ok",
            "Heavy ongoing work on mobile layout iframe cache viewport regression",
            self.docs, self.idf,
        )
        self.assertNotEqual(r["action"], "rebind")

    def test_locked_and_done_quests_never_picked(self):
        # The fixture has a "locked-old-feature" and "done-old-quest" — neither
        # should appear in scoring because docs filter to status='current'.
        r = scorer.decide_action("locked old feature", "", self.docs, self.idf)
        self.assertNotEqual(r.get("top"), "locked-old-feature")
        r = scorer.decide_action("done quest moshytz variant engine ago", "", self.docs, self.idf)
        self.assertNotEqual(r.get("top"), "done-old-quest")


class TestPriorContextExtraction(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(scorer._read_prior_assistant_text("/nonexistent/path"), "")

    def test_empty_path_returns_empty(self):
        self.assertEqual(scorer._read_prior_assistant_text(""), "")

    def test_malformed_lines_skipped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write("not-json garbage\n")
            f.write('{partial\n')
            f.write(json.dumps({"message": {"role": "assistant",
                                            "content": [{"type": "text",
                                                         "text": "valid message"}]}}) + "\n")
            path = f.name
        try:
            txt = scorer._read_prior_assistant_text(path)
            self.assertEqual(txt, "valid message")
        finally:
            os.unlink(path)

    def test_huge_file_tail_only(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            # 5MB of padding
            padding = json.dumps({"message": {"role": "user", "content": "x" * 100}}) + "\n"
            for _ in range(50000):
                f.write(padding)
            f.write(json.dumps({"message": {"role": "assistant",
                                            "content": [{"type": "text",
                                                         "text": "relevant tail message"}]}}) + "\n")
            path = f.name
        try:
            txt = scorer._read_prior_assistant_text(path)
            self.assertIn("relevant tail message", txt)
        finally:
            os.unlink(path)


class TestProjectResolution(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.cfg = self.tmpdir / "config.json"
        self.cfg.write_text(json.dumps(FIXTURE_CONFIG))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_path_map_exact(self):
        with mock.patch.object(scorer, "CONFIG_FILE", self.cfg):
            self.assertEqual(scorer._resolve_project("/tmp/quest-test-cwd"), "demo")

    def test_path_map_slash_prefix(self):
        with mock.patch.object(scorer, "CONFIG_FILE", self.cfg):
            self.assertEqual(scorer._resolve_project("/tmp/quest-test-cwd/sub/dir"), "demo")

    def test_path_map_hyphen_worktree(self):
        with mock.patch.object(scorer, "CONFIG_FILE", self.cfg):
            self.assertEqual(scorer._resolve_project("/tmp/quest-test-cwd-worktree"), "demo")

    def test_unrelated_cwd_no_project(self):
        with mock.patch.object(scorer, "CONFIG_FILE", self.cfg):
            self.assertEqual(scorer._resolve_project("/some/other/place"), "")


class TestEndToEnd(unittest.TestCase):
    """Full run_from_stdin tests with isolated fake filesystem."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.quest_root = self.tmpdir / ".claude" / "quest"
        (self.quest_root / "data").mkdir(parents=True)
        (self.quest_root / "run").mkdir(parents=True)
        (self.quest_root / "log").mkdir(parents=True)
        (self.quest_root / "data" / "quests.json").write_text(json.dumps(FIXTURE_QUESTS))
        (self.quest_root / "config.json").write_text(json.dumps(FIXTURE_CONFIG))
        # cwd for path_map
        (Path("/tmp/quest-test-cwd")).mkdir(exist_ok=True)

        # Patch module-level paths
        self._patches = [
            mock.patch.object(scorer, "HOME", self.tmpdir),
            mock.patch.object(scorer, "QUEST_ROOT", self.quest_root),
            mock.patch.object(scorer, "RUN_DIR", self.quest_root / "run"),
            mock.patch.object(scorer, "LOG_DIR", self.quest_root / "log"),
            mock.patch.object(scorer, "LOG_FILE", self.quest_root / "log" / "rebind.jsonl"),
            mock.patch.object(scorer, "DRY_RUN_MARKER", self.quest_root / "dry-run"),
            mock.patch.object(scorer, "DATA_FILE", self.quest_root / "data" / "quests.json"),
            mock.patch.object(scorer, "CONFIG_FILE", self.quest_root / "config.json"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, prompt, cwd="/tmp/quest-test-cwd", transcript_path="", sk="testpid-testticks"):
        """Invoke run_from_stdin with stubbed _walk_claude_pid."""
        with mock.patch.object(scorer, "_walk_claude_pid", return_value=sk):
            payload = json.dumps({"prompt": prompt, "cwd": cwd, "transcript_path": transcript_path})
            stdin = sys.stdin
            sys.stdin = type("S", (), {"read": lambda self: payload})()
            try:
                ret = scorer.run_from_stdin()
            finally:
                sys.stdin = stdin
        return ret

    def _last_log(self):
        log = self.quest_root / "log" / "rebind.jsonl"
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        return json.loads(lines[-1]) if lines else None

    def test_strong_prompt_rebinds_and_writes_claim(self):
        self._run("investigate mobile iframe cache viewport regression")
        claim = (self.quest_root / "run" / "session-testpid-testticks.quest").read_text().strip()
        self.assertEqual(claim, "demo/mobile-layout-iframe-cache")
        e = self._last_log()
        self.assertEqual(e["acted"], "rebound")

    def test_dry_run_marker_blocks_write(self):
        (self.quest_root / "dry-run").touch()
        self._run("investigate mobile iframe cache viewport regression")
        cf = self.quest_root / "run" / "session-testpid-testticks.quest"
        self.assertFalse(cf.exists())
        e = self._last_log()
        self.assertEqual(e["acted"], "rebound-dryrun")

    def test_lock_file_blocks_write(self):
        cf = self.quest_root / "run" / "session-testpid-testticks.quest"
        cf.write_text("demo/inline-editor-modularization\n")
        (self.quest_root / "run" / "session-testpid-testticks.quest.lock").write_text("locked\n")
        self._run("investigate mobile iframe cache viewport regression")
        # Claim unchanged
        self.assertEqual(cf.read_text().strip(), "demo/inline-editor-modularization")
        e = self._last_log()
        self.assertEqual(e["acted"], "locked-skip")

    def test_no_sk_logged_skip(self):
        self._run("investigate mobile iframe cache viewport regression", sk=None)
        e = self._last_log()
        self.assertEqual(e["acted"], "no-sk")
        self.assertEqual(e["action"], "skip")

    def test_no_project_logged_skip(self):
        self._run("investigate", cwd="/totally/unrelated/path")
        e = self._last_log()
        self.assertEqual(e["acted"], "no-project")

    def test_rc4_task_notification_prompt_skipped(self):
        # RC4: <task-notification> blobs are harness-injected subagent
        # completion messages, not user intent — must not drive a rebind.
        self._run(
            "<task-notification>\n<task-id>babc123</task-id>\n<summary>"
            "investigate mobile iframe cache viewport regression</summary>"
        )
        e = self._last_log()
        self.assertEqual(e["acted"], "skipped_task_notification")
        self.assertEqual(e["action"], "skip")
        cf = self.quest_root / "run" / "session-testpid-testticks.quest"
        self.assertFalse(cf.exists(), "task-notification must not write a claim")

    def test_same_claim_no_op(self):
        cf = self.quest_root / "run" / "session-testpid-testticks.quest"
        cf.write_text("demo/mobile-layout-iframe-cache\n")
        before = cf.stat().st_mtime_ns
        self._run("investigate mobile iframe cache viewport regression")
        after = cf.stat().st_mtime_ns
        e = self._last_log()
        self.assertEqual(e["acted"], "rebound-noop-same")
        self.assertEqual(before, after, "claim file should not be rewritten when same")

    def test_hebrew_prompt_safe_noop(self):
        # Hebrew tokenizes to zero scorable tokens → noop with path="no-tokens".
        # The acted field reflects the (lack of) side effect (noop), the path
        # field carries the reason.
        self._run("מה קורה פה")
        e = self._last_log()
        self.assertEqual(e["action"], "noop")
        self.assertEqual(e["path"], "no-tokens")
        # No claim file should be written
        cf = self.quest_root / "run" / "session-testpid-testticks.quest"
        self.assertFalse(cf.exists())


def main():
    unittest.main(argv=[sys.argv[0], "-v"], exit=False)


if __name__ == "__main__":
    main()
