"""Regression tests for the plan-anchored auto-claim (quest.py claim --plan).

Run with: python3 -m unittest test_plan_anchor
Or:       pytest -xvs ~/.claude/skills/quest/test_plan_anchor.py

Covers (plan claim-discipline-troubleshooting-dynamic-brook §8):
  (a) plan write → claim file becomes the matching quest
  (b) locked session NOT overwritten, lock NOT unlinked
  (c) no match → claim unchanged (never guess)
  (d) two current quests sharing a plan basename → ambiguous, unchanged
  (e) re-claim of same target → no-op (idempotent, no churn)
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import quest  # noqa: E402

SK = "999999-1234567"

FIXTURE_QUESTS = {
    "version": 2,
    "projects": {
        "demo": {
            "name": "Demo",
            "quests": [
                {
                    "id": "anchor-target",
                    "n": 1,
                    "name": "Anchor Target",
                    "status": "current",
                    "plan": "anchor-target-plan.md",
                },
                {
                    "id": "other-current",
                    "n": 2,
                    "name": "Other Current",
                    "status": "current",
                    "plan": "other-current-plan.md",
                },
                {
                    "id": "archived-twin",
                    "n": 3,
                    "name": "Archived Twin",
                    "status": "done",
                    # Same plan basename as anchor-target: must NOT make it ambiguous
                    # (only status==current participates in matching).
                    "plan": "anchor-target-plan.md",
                },
            ],
        },
        "otherproj": {
            "name": "Other",
            "quests": [
                {
                    "id": "multi-a",
                    "n": 1,
                    "name": "Multi A",
                    "status": "current",
                    "plan": "shared-plan.md",
                },
                {
                    "id": "multi-b",
                    "n": 2,
                    "name": "Multi B",
                    "status": "current",
                    "plan": "shared-plan.md",
                },
            ],
        },
    },
}


class PlanAnchorBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="quest-plan-anchor-"))
        self.run_dir = self.tmp / "run"
        self.run_dir.mkdir()
        self.data_file = self.tmp / "quests.json"
        self.data_file.write_text(json.dumps(FIXTURE_QUESTS), encoding="utf-8")
        self.log_file = self.tmp / "rebind.jsonl"
        self.plans = self.tmp / "plans"
        self.plans.mkdir()

        self._patches = [
            mock.patch.object(quest, "DATA", self.data_file),
            mock.patch.object(quest, "RUN", self.run_dir),
            mock.patch.object(quest, "REBIND_LOG", self.log_file),
            mock.patch.object(quest, "session_key", lambda: SK),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ----------------------------------------------------------
    def write_plan(self, name: str, project: str = "demo") -> Path:
        p = self.plans / name
        p.write_text(
            f"# Plan: {name}\n> **Project**: {project}\n\nbody\n", encoding="utf-8"
        )
        return p

    def claim_plan(self, plan_path: Path) -> int:
        args = types.SimpleNamespace(plan=str(plan_path))
        return quest.cmd_claim_plan(args)

    @property
    def claim_file(self) -> Path:
        return self.run_dir / f"session-{SK}.quest"

    @property
    def lock_file(self) -> Path:
        return self.run_dir / f"session-{SK}.quest.lock"

    def last_log(self) -> dict:
        lines = self.log_file.read_text(encoding="utf-8").strip().splitlines()
        return json.loads(lines[-1])


class TestPlanAnchorClaims(PlanAnchorBase):
    def test_a_plan_write_claims_matching_quest(self):
        plan = self.write_plan("anchor-target-plan.md")
        rc = self.claim_plan(plan)
        self.assertEqual(rc, 0)
        self.assertTrue(self.claim_file.exists(), "claim file not written")
        self.assertEqual(
            self.claim_file.read_text(encoding="utf-8").strip(),
            "demo/anchor-target",
        )
        self.assertEqual(self.last_log()["acted"], "claimed")
        self.assertEqual(self.last_log()["event"], "plan_anchor")

    def test_b_locked_session_not_overwritten(self):
        # Operator locked this session to another quest (Fix A)
        self.claim_file.write_text("demo/other-current\n", encoding="utf-8")
        self.lock_file.write_text("demo/other-current\n", encoding="utf-8")

        plan = self.write_plan("anchor-target-plan.md")
        rc = self.claim_plan(plan)
        self.assertEqual(rc, 0)
        self.assertEqual(
            self.claim_file.read_text(encoding="utf-8").strip(),
            "demo/other-current",
            "locked claim was overwritten",
        )
        self.assertTrue(self.lock_file.exists(), "lock sidecar was unlinked")
        self.assertEqual(self.last_log()["acted"], "locked-skip")


    def test_c_no_match_leaves_claim_unchanged(self):
        self.claim_file.write_text("demo/other-current\n", encoding="utf-8")
        plan = self.write_plan("no-such-plan.md")
        rc = self.claim_plan(plan)
        self.assertEqual(rc, 0)
        self.assertEqual(
            self.claim_file.read_text(encoding="utf-8").strip(),
            "demo/other-current",
            "claim changed despite no matching quest",
        )
        self.assertEqual(self.last_log()["acted"], "no-match")

    def test_d_ambiguous_multi_quest_plan_skipped(self):
        # Two CURRENT quests legitimately share one plan (MULTI-QUEST shape)
        plan = self.write_plan("shared-plan.md", project="otherproj")
        rc = self.claim_plan(plan)
        self.assertEqual(rc, 0)
        self.assertFalse(self.claim_file.exists(), "claim written despite ambiguity")
        self.assertEqual(self.last_log()["acted"], "ambiguous")

    def test_e_idempotent_reclaim_is_noop(self):
        plan = self.write_plan("anchor-target-plan.md")
        self.claim_plan(plan)
        self.assertEqual(self.last_log()["acted"], "claimed")
        before = self.claim_file.stat().st_mtime_ns
        rc = self.claim_plan(plan)
        self.assertEqual(rc, 0)
        self.assertEqual(self.last_log()["acted"], "noop")
        self.assertEqual(
            self.claim_file.stat().st_mtime_ns, before, "claim file rewritten on no-op"
        )

    def test_archived_twin_does_not_block_match(self):
        # Fixture 'archived-twin' (status=done) shares anchor-target's plan
        # basename; only current quests participate, so the match is unique.
        plan = self.write_plan("anchor-target-plan.md")
        self.claim_plan(plan)
        self.assertEqual(
            self.claim_file.read_text(encoding="utf-8").strip(),
            "demo/anchor-target",
        )

    def test_f_abs_path_match_beats_basename_stub(self):
        # Real-data class (deep-test 2026-06-11): autosync spawns a bare-name
        # codename stub next to a hand-curated quest whose plan is the ABS path
        # of the same file. Exact-abs match is strictly more specific than
        # basename match → the curated quest wins; NOT ambiguous.
        plan = self.write_plan("dup-form-plan.md")
        data = json.loads(self.data_file.read_text(encoding="utf-8"))
        data["projects"]["demo"]["quests"] += [
            {"id": "codename-stub", "n": 8, "name": "Codename Stub",
             "status": "current", "plan": "dup-form-plan.md"},
            {"id": "curated-real", "n": 9, "name": "Curated Real",
             "status": "current", "plan": str(plan)},
        ]
        self.data_file.write_text(json.dumps(data), encoding="utf-8")
        rc = self.claim_plan(plan)
        self.assertEqual(rc, 0)
        self.assertEqual(
            self.claim_file.read_text(encoding="utf-8").strip(),
            "demo/curated-real",
            "exact abs-path quest must beat the basename stub",
        )
        self.assertEqual(self.last_log()["acted"], "claimed")

    def test_g_two_same_form_matches_stay_ambiguous(self):
        # Specificity tie-break only applies across FORMS; two bare-name
        # matches (true MULTI-QUEST) must still no-op.
        plan = self.write_plan("shared-plan.md", project="otherproj")
        rc = self.claim_plan(plan)
        self.assertEqual(rc, 0)
        self.assertFalse(self.claim_file.exists())
        self.assertEqual(self.last_log()["acted"], "ambiguous")

    def test_bare_claim_unaffected_without_plan_flag(self):
        # Regression guard: a Namespace WITHOUT --plan must not enter plan mode.
        args = types.SimpleNamespace(plan="", project_id="demo",
                                     quest_id="other-current",
                                     session_name="", lock=False)
        rc = quest.cmd_claim(args)
        self.assertEqual(rc, 0)
        self.assertEqual(
            self.claim_file.read_text(encoding="utf-8").strip(),
            "demo/other-current",
        )


if __name__ == "__main__":
    unittest.main()
