#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rc_revalidate import RCRevalidationError, required_scenarios, revalidate_benchmark, selected_attempts


COMMIT = "a" * 40
HOST = "b" * 64


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def scenario_summary() -> dict:
    return {
        "version": 1,
        "source_commit": COMMIT,
        "host_fingerprint": HOST,
        "nginx_version": "1.30.4",
        "compiler": "gcc",
        "frontend": "tls-h2",
        "transport": "h2",
        "payload_bytes": 4096,
        "messages": 1,
        "backend_delay_ms": 0,
        "consumer_delay_ms": 0,
        "capacity_steps": "25,50,100,200",
        "repeat_count": 5,
        "evidence_class": "controlled",
        "boundaries_complete": True,
        "boundary_missing": {"legacy": [], "native": []},
        "ready": True,
        "reasons": [],
        "recommendation": "native_preferred",
        "decision_reasons": [],
        "capacity": {},
        "capacity_delta_percent": 10.0,
        "reference_streams": 100,
        "same_load_delta_percent": {},
        "per_repeat": [],
    }


def benchmark_fixture(root: Path, *, large8_requested: bool = False) -> Path:
    bench = root / "benchmark"
    names = ["typical", "large4m", "slow"] + (["large8m"] if large8_requested else [])
    write_json(bench / "manifest.json", {
        "repeats": 5,
        "large8m": {
            "requested": large8_requested,
            "skip_reason": "" if large8_requested else "explicit test fixture skip",
        },
    })
    selected = {}
    scenarios = {}
    for name in names:
        attempt = bench / name / "attempt-01"
        attempt.mkdir(parents=True, exist_ok=True)
        selected[name] = f"{name}/attempt-01"
        scenarios[name] = scenario_summary()
    write_json(bench / "selected-attempts.json", selected)
    write_json(bench / "rc-benchmark.json", {
        "version": 1,
        "source_commit": COMMIT,
        "host_fingerprint": HOST,
        "nginx_version": "1.30.4",
        "compiler": "gcc",
        "ready": True,
        "blockers": [],
        "scenarios": scenarios,
    })
    return bench


class SelectedAttemptTests(unittest.TestCase):
    def test_required_scenarios_include_large8_only_when_requested(self):
        self.assertEqual(
            required_scenarios({"large8m": {"requested": False, "skip_reason": "hardware limit"}}),
            ["typical", "large4m", "slow"],
        )
        self.assertEqual(
            required_scenarios({"large8m": {"requested": True, "skip_reason": ""}}),
            ["typical", "large4m", "slow", "large8m"],
        )

    def test_relative_selected_attempts_are_resolved_inside_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            bench = benchmark_fixture(Path(tmp))
            manifest = json.loads((bench / "manifest.json").read_text())
            selected = selected_attempts(bench, manifest)
            self.assertEqual(selected["typical"], (bench / "typical" / "attempt-01").resolve())
            self.assertTrue(all(path.is_relative_to(bench.resolve()) for path in selected.values()))

    def test_selected_attempt_cannot_escape_benchmark_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench = benchmark_fixture(root)
            outside = root / "outside"
            outside.mkdir()
            selected = json.loads((bench / "selected-attempts.json").read_text())
            selected["typical"] = str(outside.resolve())
            write_json(bench / "selected-attempts.json", selected)
            manifest = json.loads((bench / "manifest.json").read_text())
            with self.assertRaisesRegex(RCRevalidationError, "outside benchmark directory"):
                selected_attempts(bench, manifest)

    def test_skipped_large8_requires_non_empty_reason(self):
        with self.assertRaisesRegex(RCRevalidationError, "8 MiB"):
            required_scenarios({"large8m": {"requested": False, "skip_reason": ""}})


class RevalidationOrchestrationTests(unittest.TestCase):
    def _evaluate(self, copied: Path, *, min_repeats: int) -> dict:
        self.assertEqual(min_repeats, 5)
        return scenario_summary()

    def test_revalidation_rebuilds_all_selected_summaries_and_matches_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench = benchmark_fixture(root)
            output = root / "revalidated"
            with patch("rc_revalidate.revalidate_controlled") as raw, patch(
                "rc_revalidate.evaluate_scenario", side_effect=self._evaluate
            ):
                result = revalidate_benchmark(repo_root=root, benchmark_dir=bench, output_dir=output)
            self.assertTrue(result["valid"])
            self.assertTrue(result["original_summary_matches"])
            self.assertEqual(result["scenario_names"], ["typical", "large4m", "slow"])
            self.assertEqual(raw.call_count, 3)
            self.assertTrue((output / "rc-benchmark.revalidated.json").is_file())

    def test_tampered_saved_aggregate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench = benchmark_fixture(root)
            aggregate_path = bench / "rc-benchmark.json"
            aggregate = json.loads(aggregate_path.read_text())
            aggregate["source_commit"] = "c" * 40
            write_json(aggregate_path, aggregate)
            with patch("rc_revalidate.revalidate_controlled"), patch(
                "rc_revalidate.evaluate_scenario", side_effect=self._evaluate
            ):
                result = revalidate_benchmark(
                    repo_root=root,
                    benchmark_dir=bench,
                    output_dir=root / "revalidated",
                )
            self.assertFalse(result["valid"])
            self.assertEqual(result["reason"], "rc_raw_revalidation")
            self.assertIn("does not match aggregate", result["error"])


if __name__ == "__main__":
    unittest.main()
