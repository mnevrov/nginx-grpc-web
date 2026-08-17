#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rc import RCInputError, aggregate_scenarios, evaluate_scenario, extend_steps, parse_steps


COMMIT = "a" * 40
FINGERPRINT = "b" * 64


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def make_scenario(root: Path, *, repeats: int = 5, legacy_failed: bool = True, native_failed: bool = True) -> Path:
    write_json(root / "manifest.json", {
        "version": 1,
        "git_commit": COMMIT,
        "frontend": "tls-h2",
        "repeats": repeats,
        "nginx_version": "1.30.4",
        "build_cc": "gcc",
        "capacity_steps": "25,50,100,200",
        "transport": "text",
        "payload_bytes": 4096,
        "messages": 20,
        "backend_delay_ms": 20,
        "consumer_delay_ms": 0,
        "strict_preflight": True,
    })
    write_json(root / "decision.json", {
        "version": 1,
        "host_fingerprint": FINGERPRINT,
        "evidence_class": "controlled",
        "repeats": repeats,
        "capacity": {
            "legacy": {"min": 100.0, "median": 100.0, "max": 100.0, "cv": 0.0},
            "native": {"min": 200.0, "median": 200.0, "max": 200.0, "cv": 0.0},
        },
        "capacity_delta_percent": 100.0,
        "reference": {
            "streams": 100,
            "median_delta_percent": {
                "avg_gateway_cores": -30.0,
                "peak_rss_mib": -67.0,
                "p99_ttfd_ms": -5.0,
            },
        },
        "recommendation": "native_preferred",
        "decision_reasons": [],
    })
    for idx in range(1, repeats + 1):
        repeat = root / f"repeat-{idx:02d}"
        write_json(repeat / "host.json", {
            "strict": True,
            "valid": True,
            "fingerprint": FINGERPRINT,
        })
        write_json(repeat / "capacity.json", {
            "architectures": {
                "legacy": {
                    "max_sustainable_streams": 100,
                    "first_failed_streams": 200 if legacy_failed else None,
                },
                "native": {
                    "max_sustainable_streams": 200,
                    "first_failed_streams": 400 if native_failed else None,
                },
            }
        })
    return root


class RCScenarioTests(unittest.TestCase):
    def test_valid_controlled_scenario_requires_real_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scenario(make_scenario(Path(tmp)))
            self.assertTrue(result["boundaries_complete"])
            self.assertEqual(result["repeat_count"], 5)
            self.assertEqual(result["capacity_delta_percent"], 100.0)

    def test_native_lower_bound_is_not_final_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scenario(make_scenario(Path(tmp), native_failed=False))
            self.assertFalse(result["boundaries_complete"])
            self.assertEqual(result["boundary_missing"]["native"], [f"repeat-{i:02d}" for i in range(1, 6)])
            self.assertIn("capacity_boundary_not_reached", result["reasons"])

    def test_legacy_lower_bound_is_not_final_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scenario(make_scenario(Path(tmp), legacy_failed=False))
            self.assertFalse(result["boundaries_complete"])
            self.assertTrue(result["boundary_missing"]["legacy"])

    def test_harness_only_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_scenario(Path(tmp))
            decision = json.loads((root / "decision.json").read_text())
            decision["evidence_class"] = "harness_only"
            write_json(root / "decision.json", decision)
            with self.assertRaisesRegex(RCInputError, "evidence_class=controlled"):
                evaluate_scenario(root)

    def test_fewer_than_five_repeats_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RCInputError, "at least 5 strict repeats"):
                evaluate_scenario(make_scenario(Path(tmp), repeats=4))

    def test_mixed_host_fingerprint_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_scenario(Path(tmp))
            host = json.loads((root / "repeat-03" / "host.json").read_text())
            host["fingerprint"] = "c" * 64
            write_json(root / "repeat-03" / "host.json", host)
            with self.assertRaisesRegex(RCInputError, "do not match"):
                evaluate_scenario(root)

    def test_missing_capacity_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_scenario(Path(tmp))
            (root / "repeat-02" / "capacity.json").unlink()
            with self.assertRaisesRegex(RCInputError, "missing repeat-02 capacity"):
                evaluate_scenario(root)

    def test_string_boolean_does_not_pass_strict_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_scenario(Path(tmp))
            manifest = json.loads((root / "manifest.json").read_text())
            manifest["strict_preflight"] = "true"
            write_json(root / "manifest.json", manifest)
            with self.assertRaisesRegex(RCInputError, "JSON boolean"):
                evaluate_scenario(root)


class StaircaseTests(unittest.TestCase):
    def test_parse_and_extend_is_deterministic(self):
        steps = parse_steps("25,50,100,200,400,800,1200")
        self.assertEqual(extend_steps(steps, max_streams=5000)[-1], 2400)
        self.assertEqual(extend_steps([*steps, 2400], max_streams=5000)[-1], 4800)
        self.assertEqual(extend_steps([*steps, 2400, 4800], max_streams=5000)[-1], 5000)

    def test_ceiling_exhaustion_fails_closed(self):
        with self.assertRaisesRegex(RCInputError, "boundary not reached"):
            extend_steps([25, 50, 100], max_streams=100)

    def test_invalid_staircase_is_rejected(self):
        with self.assertRaisesRegex(RCInputError, "strictly increasing"):
            parse_steps("25,50,50,100")


class AggregateTests(unittest.TestCase):
    def test_aggregate_requires_same_commit_and_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summaries = []
            for name in ("typical", "large4m", "slow"):
                scenario = evaluate_scenario(make_scenario(root / name))
                path = root / f"{name}.json"
                write_json(path, scenario)
                summaries.append((name, path))
            result = aggregate_scenarios(summaries)
            self.assertTrue(result["ready"])
            self.assertEqual(result["blockers"], [])

    def test_aggregate_rejects_incomplete_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario = evaluate_scenario(make_scenario(root / "typical", native_failed=False))
            path = root / "typical.json"
            write_json(path, scenario)
            result = aggregate_scenarios([("typical", path)])
            self.assertFalse(result["ready"])
            self.assertIn("typical:capacity_boundary", result["blockers"])


if __name__ == "__main__":
    unittest.main()
