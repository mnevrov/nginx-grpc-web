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


def make_scenario(
    root: Path,
    *,
    repeats: int = 5,
    legacy_failed: bool = True,
    native_failed: bool = True,
    recommendation: str = "native_preferred",
    decision_reasons: list[str] | None = None,
) -> Path:
    manifest = {
        "version": 1,
        "git_commit": COMMIT,
        "frontend": "tls-h2",
        "repeats": repeats,
        "nginx_version": "1.30.4",
        "build_cc": "gcc",
        "capacity_steps": "25,50,100,200,400",
        "transport": "text",
        "payload_bytes": 4096,
        "messages": 20,
        "backend_delay_ms": 20,
        "consumer_delay_ms": 0,
        "gateway_cpuset": "2-5",
        "strict_preflight": True,
    }
    write_json(root / "manifest.json", manifest)
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
                "p99_backend_to_client_ms": -10.0,
                "error_rate": 0.0,
            },
        },
        "recommendation": recommendation,
        "decision_reasons": decision_reasons or [],
    })
    capacity_scenario = {
        "frontend": manifest["frontend"],
        "transport": manifest["transport"],
        "payload_bytes": manifest["payload_bytes"],
        "messages_per_stream": manifest["messages"],
        "backend_delay_ms": manifest["backend_delay_ms"],
        "consumer_delay_ms": manifest["consumer_delay_ms"],
        "gateway_cpuset": manifest["gateway_cpuset"],
    }
    for idx in range(1, repeats + 1):
        repeat = root / f"repeat-{idx:02d}"
        write_json(repeat / "host.json", {
            "strict": True,
            "valid": True,
            "fingerprint": FINGERPRINT,
        })
        write_json(repeat / "capacity.json", {
            "scenario": capacity_scenario,
            "architectures": {
                "legacy": {
                    "max_sustainable_streams": 100,
                    "first_failed_streams": 200 if legacy_failed else None,
                },
                "native": {
                    "max_sustainable_streams": 200,
                    "first_failed_streams": 400 if native_failed else None,
                },
            },
        })
    return root


class RCScenarioTests(unittest.TestCase):
    def test_valid_controlled_scenario_is_ready_only_with_real_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scenario(make_scenario(Path(tmp)))
            self.assertTrue(result["boundaries_complete"])
            self.assertTrue(result["ready"])
            self.assertEqual(result["repeat_count"], 5)
            self.assertEqual(result["capacity_delta_percent"], 100.0)
            self.assertEqual(result["nginx_version"], "1.30.4")
            self.assertEqual(result["compiler"], "gcc")

    def test_native_lower_bound_is_not_final_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scenario(make_scenario(Path(tmp), native_failed=False))
            self.assertFalse(result["boundaries_complete"])
            self.assertFalse(result["ready"])
            self.assertEqual(result["boundary_missing"]["native"], [f"repeat-{i:02d}" for i in range(1, 6)])
            self.assertIn("capacity_boundary_not_reached", result["reasons"])

    def test_legacy_lower_bound_is_not_final_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scenario(make_scenario(Path(tmp), legacy_failed=False))
            self.assertFalse(result["boundaries_complete"])
            self.assertFalse(result["ready"])
            self.assertTrue(result["boundary_missing"]["legacy"])

    def test_inconclusive_decision_is_not_ready_even_with_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scenario(make_scenario(Path(tmp), recommendation="inconclusive"))
            self.assertTrue(result["boundaries_complete"])
            self.assertFalse(result["ready"])
            self.assertIn("decision_inconclusive", result["reasons"])

    def test_decision_reasons_make_scenario_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scenario(make_scenario(Path(tmp), decision_reasons=["latency_guardrail"]))
            self.assertFalse(result["ready"])
            self.assertIn("decision_reasons_present", result["reasons"])

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

    def test_manifest_repeat_count_must_match_raw_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_scenario(Path(tmp))
            manifest = json.loads((root / "manifest.json").read_text())
            manifest["repeats"] = 6
            write_json(root / "manifest.json", manifest)
            with self.assertRaisesRegex(RCInputError, "manifest repeat count"):
                evaluate_scenario(root)

    def test_decision_repeat_count_must_match_raw_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_scenario(Path(tmp))
            decision = json.loads((root / "decision.json").read_text())
            decision["repeats"] = 4
            write_json(root / "decision.json", decision)
            with self.assertRaisesRegex(RCInputError, "decision repeat count"):
                evaluate_scenario(root)

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

    def test_capacity_scenario_must_match_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_scenario(Path(tmp))
            path = root / "repeat-02" / "capacity.json"
            capacity = json.loads(path.read_text())
            capacity["scenario"]["payload_bytes"] = 8192
            write_json(path, capacity)
            with self.assertRaisesRegex(RCInputError, "scenario mismatch for payload_bytes"):
                evaluate_scenario(root)

    def test_failed_level_must_be_above_sustainable_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_scenario(Path(tmp))
            path = root / "repeat-01" / "capacity.json"
            capacity = json.loads(path.read_text())
            capacity["architectures"]["legacy"]["first_failed_streams"] = 100
            write_json(path, capacity)
            with self.assertRaisesRegex(RCInputError, "must be greater than max_sustainable_streams"):
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
    def _scenario_summary(self, root: Path, name: str, **kwargs) -> Path:
        scenario = evaluate_scenario(make_scenario(root / name, **kwargs))
        path = root / f"{name}.json"
        write_json(path, scenario)
        return path

    def test_aggregate_requires_same_commit_host_nginx_and_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summaries = [(name, self._scenario_summary(root, name)) for name in ("typical", "large4m", "slow")]
            result = aggregate_scenarios(summaries)
            self.assertTrue(result["ready"])
            self.assertEqual(result["blockers"], [])
            self.assertEqual(result["nginx_version"], "1.30.4")
            self.assertEqual(result["compiler"], "gcc")

    def test_aggregate_rejects_incomplete_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._scenario_summary(root, "typical", native_failed=False)
            result = aggregate_scenarios([("typical", path)])
            self.assertFalse(result["ready"])
            self.assertIn("typical:capacity_boundary", result["blockers"])
            self.assertIn("typical:not_ready", result["blockers"])

    def test_aggregate_rejects_inconclusive_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._scenario_summary(root, "typical", recommendation="inconclusive")
            result = aggregate_scenarios([("typical", path)])
            self.assertFalse(result["ready"])
            self.assertIn("typical:not_ready", result["blockers"])

    def test_aggregate_rejects_mixed_nginx_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            one = self._scenario_summary(root, "typical")
            two = self._scenario_summary(root, "large4m")
            summary = json.loads(two.read_text())
            summary["nginx_version"] = "1.31.3"
            write_json(two, summary)
            result = aggregate_scenarios([("typical", one), ("large4m", two)])
            self.assertFalse(result["ready"])
            self.assertIn("mixed_nginx_version", result["blockers"])

    def test_aggregate_rejects_mixed_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            one = self._scenario_summary(root, "typical")
            two = self._scenario_summary(root, "slow")
            summary = json.loads(two.read_text())
            summary["compiler"] = "clang"
            write_json(two, summary)
            result = aggregate_scenarios([("typical", one), ("slow", two)])
            self.assertFalse(result["ready"])
            self.assertIn("mixed_compiler", result["blockers"])


if __name__ == "__main__":
    unittest.main()
