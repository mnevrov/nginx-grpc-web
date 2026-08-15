#!/usr/bin/env python3
from __future__ import annotations

import unittest

from soak import SoakPolicy, evaluate_soak, linear_slope_per_hour


def sample(second: float, rss_mib: float) -> dict:
    return {
        "timestamp": second,
        "container": "nginx",
        "rss_mib": rss_mib,
        "memory_current_mib": rss_mib + 8.0,
    }


def healthy_events(**overrides) -> dict:
    base = {
        "steady": {"runs": 1, "unexpected_errors": 0},
        "churn": {"runs": 5, "unexpected_errors": 0},
        "cancel": {
            "runs": 5,
            "expected_cancellations": 50,
            "observed_cancellations": 50,
            "unexpected_errors": 0,
        },
        "backend_restart": {
            "attempted": 1,
            "recovery_success": True,
        },
        "transport_reset": {
            "attempted": 10,
            "recovery_success": True,
        },
        "final_probe": {"success": True},
        "nginx": {
            "master_pid_start": 1,
            "master_pid_end": 1,
            "container_restart_count_start": 0,
            "container_restart_count_end": 0,
        },
    }
    base.update(overrides)
    return base


POLICY = SoakPolicy(
    min_duration_seconds=60.0,
    min_samples=5,
    warmup_seconds=10.0,
    max_rss_slope_mib_per_hour=8.0,
    max_rss_growth_mib=32.0,
)


class SoakMathTests(unittest.TestCase):
    def test_linear_slope_is_reported_per_hour(self):
        points = [(0.0, 100.0), (1800.0, 102.0), (3600.0, 104.0)]
        self.assertAlmostEqual(linear_slope_per_hour(points), 4.0, places=6)

    def test_flat_series_has_zero_slope(self):
        points = [(0.0, 100.0), (30.0, 100.0), (60.0, 100.0)]
        self.assertAlmostEqual(linear_slope_per_hour(points), 0.0, places=6)


class SoakEvaluationTests(unittest.TestCase):
    def controlled_timeline(self) -> dict:
        return {
            "strict": True,
            "samples": [
                sample(0, 100.0),
                sample(10, 101.0),
                sample(20, 101.1),
                sample(30, 101.1),
                sample(45, 101.1),
                sample(60, 101.1),
                sample(75, 101.1),
            ],
            "events": healthy_events(),
        }

    def test_controlled_healthy_soak_passes(self):
        result = evaluate_soak(self.controlled_timeline(), POLICY)
        self.assertEqual(result["evidence_class"], "controlled")
        self.assertEqual(result["verdict"], "soak_pass")
        self.assertEqual(result["reasons"], [])

    def test_shared_ci_never_becomes_production_evidence(self):
        timeline = self.controlled_timeline()
        timeline["strict"] = False
        result = evaluate_soak(timeline, POLICY)
        self.assertEqual(result["evidence_class"], "harness_only")
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertIn("harness_only", result["reasons"])

    def test_positive_memory_slope_fails_controlled_soak(self):
        timeline = self.controlled_timeline()
        timeline["samples"] = [
            sample(0, 100.0),
            sample(10, 100.0),
            sample(20, 101.0),
            sample(30, 102.0),
            sample(45, 103.5),
            sample(60, 105.0),
            sample(75, 106.5),
        ]
        result = evaluate_soak(timeline, POLICY)
        self.assertEqual(result["verdict"], "soak_fail")
        self.assertIn("rss_slope", result["reasons"])

    def test_backend_must_recover_after_restart(self):
        timeline = self.controlled_timeline()
        events = healthy_events()
        events["backend_restart"] = {"attempted": 1, "recovery_success": False}
        timeline["events"] = events
        result = evaluate_soak(timeline, POLICY)
        self.assertEqual(result["verdict"], "soak_fail")
        self.assertIn("backend_recovery", result["reasons"])

    def test_nginx_master_or_container_restart_fails(self):
        timeline = self.controlled_timeline()
        events = healthy_events()
        events["nginx"] = {
            "master_pid_start": 1,
            "master_pid_end": 7,
            "container_restart_count_start": 0,
            "container_restart_count_end": 1,
        }
        timeline["events"] = events
        result = evaluate_soak(timeline, POLICY)
        self.assertEqual(result["verdict"], "soak_fail")
        self.assertIn("nginx_restart", result["reasons"])

    def test_missing_expected_cancellation_is_failure(self):
        timeline = self.controlled_timeline()
        events = healthy_events()
        events["cancel"] = {
            "runs": 5,
            "expected_cancellations": 50,
            "observed_cancellations": 49,
            "unexpected_errors": 0,
        }
        timeline["events"] = events
        result = evaluate_soak(timeline, POLICY)
        self.assertEqual(result["verdict"], "soak_fail")
        self.assertIn("cancellation_accounting", result["reasons"])


if __name__ == "__main__":
    unittest.main()
