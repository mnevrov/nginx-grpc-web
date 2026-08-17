#!/usr/bin/env python3
from __future__ import annotations

import copy
import unittest

from m15 import evaluate


COMMIT = "a" * 40
HOST = "b" * 64
SHA = "c" * 64


def inputs(duration: float = 28801.0):
    benchmark_manifest = {
        "git_commit": COMMIT,
        "host_fingerprint": HOST,
        "large8m": {"requested": True, "skip_reason": ""},
    }
    benchmark = {
        "source_commit": COMMIT,
        "host_fingerprint": HOST,
        "ready": True,
        "blockers": [],
    }
    soak = {
        "ready": True,
        "source_commit": COMMIT,
        "host_fingerprint": HOST,
        "duration_seconds": duration,
    }
    staging = {
        "source_commit": COMMIT,
        "verdict": "staging_pass",
        "package": {"sha256": SHA},
    }
    release = {
        "source_commit": COMMIT,
        "evidence_class": "controlled",
        "verdict": "release_candidate",
        "mechanics_pass": True,
        "blockers": [],
        "raw_revalidation": {"valid": True},
        "controlled": {"host_fingerprint": HOST},
        "soak": {"host_fingerprint": HOST},
        "artifact": {"sha256": SHA},
    }
    return benchmark_manifest, benchmark, soak, staging, release


def run(values, waiver=None):
    return evaluate(
        benchmark_manifest=values[0],
        benchmark=values[1],
        soak=values[2],
        staging=values[3],
        release_evidence=values[4],
        eight_hour_waiver=waiver,
    )


class M15EvidenceTests(unittest.TestCase):
    def test_full_eight_hour_evidence_is_ready_for_manual_release(self):
        result = run(inputs())
        self.assertTrue(result["ready"])
        self.assertEqual(result["verdict"], "ready_for_manual_release")
        self.assertEqual(result["blockers"], [])

    def test_two_hour_soak_requires_explicit_waiver(self):
        result = run(inputs(7205))
        self.assertFalse(result["ready"])
        self.assertIn("eight_hour_soak_or_waiver", result["blockers"])

    def test_two_hour_soak_with_waiver_is_ready_and_advisory(self):
        result = run(inputs(7205), waiver="release committee accepted 2h soak for this RC")
        self.assertTrue(result["ready"])
        self.assertIn("eight_hour_soak_waived", result["advisory"])

    def test_harness_only_m14_evidence_is_rejected(self):
        values = inputs()
        values[4]["evidence_class"] = "harness_only"
        values[4]["verdict"] = "inconclusive"
        values[4]["raw_revalidation"] = {"valid": None, "skipped": "harness_only"}
        result = run(values)
        self.assertFalse(result["ready"])
        self.assertIn("m14_not_controlled", result["blockers"])
        self.assertIn("m14_verdict", result["blockers"])
        self.assertIn("m14_raw_revalidation", result["blockers"])

    def test_staging_must_use_same_module_sha_as_release_bundle(self):
        values = inputs()
        values[3]["package"]["sha256"] = "d" * 64
        result = run(values)
        self.assertFalse(result["ready"])
        self.assertIn("staging_release_artifact_mismatch", result["blockers"])

    def test_benchmark_and_release_hosts_must_match(self):
        values = inputs()
        values[4]["controlled"]["host_fingerprint"] = "e" * 64
        result = run(values)
        self.assertFalse(result["ready"])
        self.assertIn("m14_controlled_host", result["blockers"])

    def test_large8m_requires_run_or_explicit_reason(self):
        values = inputs()
        values[0]["large8m"] = {"requested": False, "skip_reason": ""}
        result = run(values)
        self.assertFalse(result["ready"])
        self.assertIn("large8m_no_run_or_reason", result["blockers"])

    def test_explicit_large8m_skip_reason_is_accepted(self):
        values = inputs()
        values[0]["large8m"] = {
            "requested": False,
            "skip_reason": "host memory budget cannot support a meaningful 8 MiB staircase",
        }
        result = run(values)
        self.assertTrue(result["ready"])
        self.assertFalse(result["large8m_requested"])

    def test_failed_staging_blocks_release(self):
        values = inputs()
        values[3]["verdict"] = "blocked"
        result = run(values)
        self.assertFalse(result["ready"])
        self.assertIn("staging_not_ready", result["blockers"])

    def test_input_objects_are_not_mutated(self):
        values = inputs()
        before = copy.deepcopy(values)
        run(values)
        self.assertEqual(values, before)


if __name__ == "__main__":
    unittest.main()
