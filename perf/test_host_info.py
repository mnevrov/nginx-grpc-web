#!/usr/bin/env python3
from __future__ import annotations

import unittest

from host_info import build_fingerprint, parse_cpuset, validate_preflight


class HostInfoTests(unittest.TestCase):
    def test_parse_cpuset_expands_ranges(self):
        self.assertEqual(parse_cpuset("0-2,5,8-9"), {0, 1, 2, 5, 8, 9})

    def test_fingerprint_ignores_timestamp_and_hostname(self):
        base = {
            "timestamp_utc": "2026-08-15T00:00:00Z",
            "hostname": "bench-a",
            "kernel": "6.17.0",
            "machine": "x86_64",
            "cpu_model": "Example CPU",
            "online_cpus": "0-15",
            "memory_bytes": 68719476736,
            "docker_version": "28.0.0",
            "cgroup_version": "2",
            "gateway_cpuset": "0-3",
            "backend_cpuset": "4-7",
            "loadgen_cpuset": "8-11",
            "cpu_governors": ["performance"],
        }
        other = {**base, "timestamp_utc": "2026-08-16T00:00:00Z", "hostname": "bench-b"}
        self.assertEqual(build_fingerprint(base), build_fingerprint(other))

    def test_strict_preflight_rejects_overlapping_cpu_sets(self):
        issues = validate_preflight(
            {
                "online_cpus": "0-15",
                "gateway_cpuset": "0-3",
                "backend_cpuset": "4-7",
                "loadgen_cpuset": "3,8-9",
                "cpu_governors": ["performance"],
                "cgroup_version": "2",
            },
            strict=True,
        )
        self.assertTrue(any(item["level"] == "error" and item["code"] == "cpuset_overlap" for item in issues))

    def test_strict_preflight_requires_all_three_cpu_sets(self):
        issues = validate_preflight(
            {
                "online_cpus": "0-15",
                "gateway_cpuset": "",
                "backend_cpuset": "",
                "loadgen_cpuset": "",
                "cpu_governors": ["performance"],
                "cgroup_version": "2",
            },
            strict=True,
        )
        codes = {item["code"] for item in issues if item["level"] == "error"}
        self.assertIn("gateway_cpuset_missing", codes)
        self.assertIn("backend_cpuset_missing", codes)
        self.assertIn("loadgen_cpuset_missing", codes)

    def test_preflight_rejects_offline_configured_cpu(self):
        issues = validate_preflight(
            {
                "online_cpus": "0-7",
                "gateway_cpuset": "0-3",
                "backend_cpuset": "4-5",
                "loadgen_cpuset": "6-8",
                "cpu_governors": ["performance"],
                "cgroup_version": "2",
            },
            strict=True,
        )
        self.assertTrue(
            any(
                item["level"] == "error"
                and item["code"] == "cpuset_offline"
                and "8" in item["message"]
                for item in issues
            )
        )


if __name__ == "__main__":
    unittest.main()
