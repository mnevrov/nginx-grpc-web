#!/usr/bin/env python3
from __future__ import annotations

import copy
import unittest

from evidence import ReleasePolicy, evaluate_release, render_markdown


COMMIT = "a" * 40
SHA256 = "b" * 64


def valid_bundle() -> dict:
    return {
        "release_version": "v0.1.0",
        "source": {"commit": COMMIT, "dirty": False},
        "gates": {
            "compatibility": {"passed": True, "commit": COMMIT},
            "protocol": {"passed": True, "commit": COMMIT},
            "differential": {"passed": True, "commit": COMMIT},
            "browser": {"passed": True, "commit": COMMIT},
            "hardening": {"passed": True, "commit": COMMIT},
        },
        "artifact": {
            "declared_sha256": SHA256,
            "actual_sha256": SHA256,
            "manifest": {
                "module": "ngx_http_grpc_web_module.so",
                "source_commit": COMMIT,
                "nginx_version": "1.30.4",
                "compiler": "gcc",
                "platform": "linux-x86_64",
                "build_mode": "--with-compat",
            },
        },
        "controlled": {
            "manifest": {
                "git_commit": COMMIT,
                "nginx_version": "1.30.4",
                "build_cc": "gcc",
                "strict_preflight": True,
            },
            "decision": {
                "evidence_class": "controlled",
                "recommendation": "native_preferred",
                "host_fingerprint": "host-a",
                "decision_reasons": [],
            },
        },
        "soak": {
            "manifest": {
                "git_commit": COMMIT,
                "strict": True,
                "nginx_version": "1.30.4",
                "build_cc": "gcc",
                "target_duration_seconds": 7200,
            },
            "report": {
                "evidence_class": "controlled",
                "verdict": "soak_pass",
                "duration_seconds": 7205,
                "events": {
                    "host": {
                        "strict": True,
                        "valid": True,
                        "fingerprint": "host-a",
                    }
                },
            },
        },
    }


class ReleaseEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ReleasePolicy()

    def test_valid_controlled_bundle_becomes_release_candidate(self):
        result = evaluate_release(valid_bundle(), self.policy)
        self.assertEqual(result["evidence_class"], "controlled")
        self.assertEqual(result["verdict"], "release_candidate")
        self.assertTrue(result["mechanics_pass"])
        self.assertEqual(result["blockers"], [])
        self.assertIn("rc_soak_8h_recommended", result["advisory"])
        self.assertEqual(result["artifact"]["source_commit"], COMMIT)
        self.assertEqual(result["controlled"]["source_commit"], COMMIT)
        self.assertEqual(result["soak"]["source_commit"], COMMIT)

    def test_eight_hour_soak_clears_recommendation(self):
        bundle = valid_bundle()
        bundle["soak"]["report"]["duration_seconds"] = 28801
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "release_candidate")
        self.assertNotIn("rc_soak_8h_recommended", result["advisory"])

    def test_checksum_mismatch_fails_closed(self):
        bundle = valid_bundle()
        bundle["artifact"]["actual_sha256"] = "c" * 64
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("artifact_checksum_mismatch", result["blockers"])

    def test_checksum_format_is_enforced(self):
        bundle = valid_bundle()
        bundle["artifact"]["declared_sha256"] = "not-a-sha"
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("artifact_checksum_format", result["blockers"])

    def test_stale_controlled_commit_is_rejected(self):
        bundle = valid_bundle()
        bundle["controlled"]["manifest"]["git_commit"] = "d" * 40
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("controlled_commit", result["blockers"])

    def test_stale_soak_commit_is_rejected(self):
        bundle = valid_bundle()
        bundle["soak"]["manifest"]["git_commit"] = "e" * 40
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("soak_commit", result["blockers"])

    def test_controlled_and_soak_host_fingerprints_must_match(self):
        bundle = valid_bundle()
        bundle["soak"]["report"]["events"]["host"]["fingerprint"] = "host-b"
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("host_fingerprint", result["blockers"])

    def test_strict_soak_minimum_duration_is_enforced(self):
        bundle = valid_bundle()
        bundle["soak"]["report"]["duration_seconds"] = 7199
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("soak_duration", result["blockers"])

    def test_invalid_duration_type_is_rejected_without_truthiness(self):
        bundle = valid_bundle()
        bundle["soak"]["report"]["duration_seconds"] = {"seconds": 7205}
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("soak_duration_value", result["blockers"])

    def test_harness_only_cannot_escalate_to_release_candidate(self):
        bundle = valid_bundle()
        bundle["controlled"]["decision"].update({
            "evidence_class": "harness_only",
            "recommendation": "inconclusive",
            "host_fingerprint": "ci-host",
        })
        bundle["soak"]["manifest"]["strict"] = False
        bundle["soak"]["report"] = {
            "evidence_class": "harness_only",
            "verdict": "inconclusive",
            "duration_seconds": 8,
            "events": {
                "host": {"strict": False, "valid": True, "fingerprint": "ci-host"}
            },
        }
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["evidence_class"], "harness_only")
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertTrue(result["mechanics_pass"])
        self.assertIn("harness_only", result["advisory"])

    def test_missing_compatibility_gate_is_a_blocker(self):
        bundle = valid_bundle()
        del bundle["gates"]["compatibility"]
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("gate_compatibility_missing", result["blockers"])

    def test_missing_browser_gate_is_a_blocker(self):
        bundle = valid_bundle()
        del bundle["gates"]["browser"]
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("gate_browser_missing", result["blockers"])

    def test_gate_from_different_commit_is_a_blocker(self):
        bundle = valid_bundle()
        bundle["gates"]["protocol"]["commit"] = "f" * 40
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("gate_protocol_commit", result["blockers"])

    def test_string_false_gate_cannot_become_true(self):
        bundle = valid_bundle()
        bundle["gates"]["hardening"]["passed"] = "false"
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("gate_hardening_invalid", result["blockers"])
        self.assertFalse(result["gates"]["hardening"]["passed"])

    def test_string_true_strict_flag_is_not_accepted(self):
        bundle = valid_bundle()
        bundle["soak"]["manifest"]["strict"] = "true"
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("soak_not_strict", result["blockers"])

    def test_string_true_host_preflight_is_not_accepted(self):
        bundle = valid_bundle()
        bundle["soak"]["report"]["events"]["host"]["valid"] = "true"
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("soak_host_preflight", result["blockers"])

    def test_wrong_nginx_target_is_rejected_across_provenance(self):
        bundle = valid_bundle()
        bundle["artifact"]["manifest"]["nginx_version"] = "1.31.3"
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("artifact_nginx_version", result["blockers"])

    def test_dirty_tree_is_rejected(self):
        bundle = valid_bundle()
        bundle["source"]["dirty"] = True
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("dirty_tree", result["blockers"])

    def test_missing_dirty_state_is_rejected(self):
        bundle = valid_bundle()
        del bundle["source"]["dirty"]
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("source_dirty_state", result["blockers"])

    def test_controlled_inconclusive_decision_blocks_candidate(self):
        bundle = valid_bundle()
        bundle["controlled"]["decision"]["recommendation"] = "inconclusive"
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("controlled_decision", result["blockers"])

    def test_unknown_evidence_class_is_blocked(self):
        bundle = valid_bundle()
        bundle["controlled"]["decision"]["evidence_class"] = "trusted"
        result = evaluate_release(bundle, self.policy)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("controlled_evidence_class", result["blockers"])

    def test_malformed_required_object_raises(self):
        bundle = valid_bundle()
        bundle["artifact"]["manifest"] = None
        with self.assertRaisesRegex(ValueError, "artifact.manifest must be an object"):
            evaluate_release(bundle, self.policy)

    def test_unknown_policy_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown release policy fields"):
            ReleasePolicy.from_dict({"not_a_policy_field": True})

    def test_wrong_policy_numeric_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "min_strict_soak_seconds must be a finite number"):
            ReleasePolicy.from_dict({"min_strict_soak_seconds": "7200"})

    def test_markdown_exposes_verdict_and_blockers(self):
        bundle = valid_bundle()
        bundle["artifact"]["actual_sha256"] = "c" * 64
        result = evaluate_release(bundle, self.policy)
        text = render_markdown(result)
        self.assertIn("**`blocked`**", text)
        self.assertIn("`artifact_checksum_mismatch`", text)
        self.assertIn("`compatibility`", text)

    def test_evaluation_does_not_mutate_input(self):
        bundle = valid_bundle()
        before = copy.deepcopy(bundle)
        evaluate_release(bundle, self.policy)
        self.assertEqual(bundle, before)


if __name__ == "__main__":
    unittest.main()
