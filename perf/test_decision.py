#!/usr/bin/env python3
from __future__ import annotations

import unittest

from decision import DecisionPolicy, aggregate_repeats, render_markdown


def capacity_result(legacy: int, native: int, *, fingerprint: str = "host-a", latency_delta: float = -10.0,
                    cpu_delta: float = -20.0, rss_delta: float = -30.0) -> dict:
    return {
        "host_fingerprint": fingerprint,
        "scenario": {
            "frontend": "tls-h2",
            "transport": "text",
            "payload_bytes": 4096,
            "messages_per_stream": 20,
            "backend_delay_ms": 20,
            "consumer_delay_ms": 0,
            "gateway_cpuset": "0-3",
        },
        "architectures": {
            "legacy": {"max_sustainable_streams": legacy},
            "native": {"max_sustainable_streams": native},
        },
        "reference": {
            "streams": min(legacy, native),
            "delta_percent": {
                "p99_ttfd_ms": latency_delta,
                "p99_backend_to_client_ms": latency_delta,
                "avg_gateway_cores": cpu_delta,
                "peak_rss_mib": rss_delta,
                "error_rate": 0.0,
            },
        },
    }


class DecisionAggregationTests(unittest.TestCase):
    def test_repeated_capacity_uses_median_and_spread(self):
        result = aggregate_repeats(
            [
                capacity_result(100, 150),
                capacity_result(100, 160),
                capacity_result(110, 160),
            ],
            DecisionPolicy(min_repeats=3),
        )
        self.assertEqual(result["capacity"]["legacy"]["median"], 100)
        self.assertEqual(result["capacity"]["native"]["median"], 160)
        self.assertAlmostEqual(result["capacity_delta_percent"], 60.0)
        self.assertEqual(result["reference"]["streams"], 100)

    def test_mixed_host_fingerprints_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "host fingerprint"):
            aggregate_repeats(
                [capacity_result(100, 150, fingerprint="host-a"), capacity_result(100, 150, fingerprint="host-b")],
                DecisionPolicy(min_repeats=2),
            )

    def test_unstable_capacity_makes_decision_inconclusive(self):
        result = aggregate_repeats(
            [capacity_result(50, 100), capacity_result(100, 100), capacity_result(200, 100)],
            DecisionPolicy(min_repeats=3, max_capacity_cv=0.20),
        )
        self.assertEqual(result["recommendation"], "inconclusive")
        self.assertIn("capacity_variance", result["decision_reasons"])

    def test_native_is_preferred_only_with_benefit_and_latency_guardrails(self):
        policy = DecisionPolicy(
            min_repeats=3,
            min_capacity_gain_percent=10.0,
            min_cpu_saving_percent=10.0,
            min_rss_saving_percent=10.0,
            max_p99_ttfd_regression_percent=5.0,
            max_p99_backend_to_client_regression_percent=5.0,
        )
        good = aggregate_repeats([capacity_result(100, 150) for _ in range(3)], policy)
        self.assertEqual(good["recommendation"], "native_preferred")

        bad_latency = aggregate_repeats(
            [capacity_result(100, 150, latency_delta=8.0) for _ in range(3)], policy
        )
        self.assertEqual(bad_latency["recommendation"], "inconclusive")
        self.assertIn("latency_guardrail", bad_latency["decision_reasons"])

    def test_markdown_states_controlled_host_not_ci_claim(self):
        result = aggregate_repeats(
            [capacity_result(100, 150) for _ in range(3)],
            DecisionPolicy(min_repeats=3),
        )
        text = render_markdown(result)
        self.assertIn("Controlled-host architecture decision", text)
        self.assertIn("native_preferred", text)
        self.assertIn("host-a", text)


if __name__ == "__main__":
    unittest.main()
