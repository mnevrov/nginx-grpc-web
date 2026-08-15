#!/usr/bin/env python3
from __future__ import annotations

import unittest

from check import apply_revalidation


class RevalidationVerdictBindingTests(unittest.TestCase):
    def controlled_candidate(self) -> dict:
        return {
            "evidence_class": "controlled",
            "verdict": "release_candidate",
            "mechanics_pass": True,
            "blockers": [],
            "advisory": [],
        }

    def harness_result(self) -> dict:
        return {
            "evidence_class": "harness_only",
            "verdict": "inconclusive",
            "mechanics_pass": True,
            "blockers": [],
            "advisory": ["harness_only"],
        }

    def test_controlled_candidate_requires_valid_raw_revalidation(self):
        result = apply_revalidation(self.controlled_candidate(), {"version": 1, "valid": True})
        self.assertEqual(result["verdict"], "release_candidate")
        self.assertTrue(result["mechanics_pass"])
        self.assertEqual(result["blockers"], [])

    def test_failed_controlled_revalidation_blocks_release(self):
        result = apply_revalidation(
            self.controlled_candidate(),
            {"version": 1, "valid": False, "reason": "raw_revalidation", "error": "mismatch"},
        )
        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["mechanics_pass"])
        self.assertIn("raw_revalidation", result["blockers"])

    def test_missing_controlled_revalidation_pass_is_blocker(self):
        result = apply_revalidation(self.controlled_candidate(), {"version": 1})
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("raw_revalidation", result["blockers"])

    def test_harness_only_explicit_skip_remains_inconclusive(self):
        result = apply_revalidation(
            self.harness_result(),
            {"version": 1, "valid": None, "skipped": "harness_only"},
        )
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertTrue(result["mechanics_pass"])
        self.assertEqual(result["blockers"], [])

    def test_harness_only_cannot_use_implicit_revalidation_skip(self):
        result = apply_revalidation(self.harness_result(), {"version": 1, "valid": None})
        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["mechanics_pass"])
        self.assertIn("revalidation_not_harness_only", result["blockers"])

    def test_harness_failed_revalidation_is_blocked(self):
        result = apply_revalidation(
            self.harness_result(),
            {"version": 1, "valid": False, "error": "broken input"},
        )
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("raw_revalidation", result["blockers"])


if __name__ == "__main__":
    unittest.main()
