#!/usr/bin/env python3
from __future__ import annotations

import unittest

from capacity import SLO, classify_metrics, evaluate_capacity


def metrics(**overrides):
    base = {
        "streams_requested": 20,
        "streams_completed": 20,
        "errors": 0,
        "error_rate": 0.0,
        "p99_ttfd_ms": 40.0,
        "p99_backend_to_client_ms": 20.0,
        "avg_gateway_cores": 0.5,
        "peak_rss_mib": 128.0,
    }
    base.update(overrides)
    return base


def row(streams, *, legacy=None, native=None):
    return {
        "frontend": "tls-h2",
        "transport": "text",
        "payload_bytes": 4096,
        "streams": streams,
        "messages_per_stream": 20,
        "backend_delay_ms": 20,
        "consumer_delay_ms": 0,
        "legacy": legacy or metrics(streams_requested=streams * 2, streams_completed=streams * 2),
        "native": native or metrics(streams_requested=streams * 2, streams_completed=streams * 2),
    }


SLO_FIXTURE = SLO(
    max_error_rate=0.01,
    max_p99_backend_to_client_ms=50.0,
    max_p99_ttfd_ms=100.0,
    max_avg_gateway_cores=1.0,
    max_peak_rss_mib=256.0,
)


class CapacityClassificationTests(unittest.TestCase):
    def test_metrics_inside_all_limits_pass(self):
        result = classify_metrics(metrics(), SLO_FIXTURE)
        self.assertTrue(result["pass"])
        self.assertEqual(result["reasons"], [])

    def test_each_slo_violation_is_reported(self):
        result = classify_metrics(
            metrics(
                error_rate=0.02,
                p99_backend_to_client_ms=55.0,
                p99_ttfd_ms=120.0,
                avg_gateway_cores=1.2,
                peak_rss_mib=300.0,
            ),
            SLO_FIXTURE,
        )
        self.assertFalse(result["pass"])
        self.assertEqual(
            set(result["reasons"]),
            {
                "error_rate",
                "p99_backend_to_client_ms",
                "p99_ttfd_ms",
                "avg_gateway_cores",
                "peak_rss_mib",
            },
        )

    def test_capacity_stops_at_first_failure_even_if_later_point_passes(self):
        rows = [
            row(10),
            row(20),
            row(40, legacy=metrics(error_rate=0.05)),
            row(80),
        ]
        result = evaluate_capacity(
            {"rows": rows},
            SLO_FIXTURE,
            frontend="tls-h2",
            transport="text",
            payload_bytes=4096,
            messages_per_stream=20,
            backend_delay_ms=20,
            consumer_delay_ms=0,
        )
        self.assertEqual(result["architectures"]["legacy"]["max_sustainable_streams"], 20)
        self.assertEqual(result["architectures"]["legacy"]["first_failed_streams"], 40)
        self.assertEqual(result["architectures"]["native"]["max_sustainable_streams"], 80)

    def test_capacity_advantage_uses_sustainable_levels(self):
        rows = [
            row(10),
            row(20),
            row(40, legacy=metrics(p99_backend_to_client_ms=60.0)),
            row(80, legacy=metrics(p99_backend_to_client_ms=70.0), native=metrics(p99_backend_to_client_ms=60.0)),
        ]
        result = evaluate_capacity(
            {"rows": rows},
            SLO_FIXTURE,
            frontend="tls-h2",
            transport="text",
            payload_bytes=4096,
            messages_per_stream=20,
            backend_delay_ms=20,
            consumer_delay_ms=0,
        )
        self.assertEqual(result["architectures"]["legacy"]["max_sustainable_streams"], 20)
        self.assertEqual(result["architectures"]["native"]["max_sustainable_streams"], 40)
        self.assertEqual(result["capacity_delta_percent"], 100.0)

    def test_scenario_dimensions_are_not_mixed(self):
        rows = [
            row(10),
            {**row(100), "frontend": "http1"},
        ]
        result = evaluate_capacity(
            {"rows": rows},
            SLO_FIXTURE,
            frontend="tls-h2",
            transport="text",
            payload_bytes=4096,
            messages_per_stream=20,
            backend_delay_ms=20,
            consumer_delay_ms=0,
        )
        self.assertEqual([p["streams"] for p in result["architectures"]["native"]["points"]], [10])


if __name__ == "__main__":
    unittest.main()
