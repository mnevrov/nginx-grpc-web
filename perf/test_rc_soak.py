#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rc_soak import RCSoakError, evaluate_link


COMMIT = "a" * 40
FINGERPRINT = "b" * 64


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def fixture(root: Path, *, duration: float = 7205.0) -> tuple[Path, Path]:
    benchmark = root / "benchmark" / "manifest.json"
    soak = root / "soak"
    write_json(benchmark, {
        "git_commit": COMMIT,
        "nginx_version": "1.30.4",
        "build_cc": "gcc",
        "host_fingerprint": FINGERPRINT,
    })
    write_json(soak / "manifest.json", {
        "git_commit": COMMIT,
        "strict": True,
        "nginx_version": "1.30.4",
        "build_cc": "gcc",
        "target_duration_seconds": 7200,
    })
    write_json(soak / "host.json", {
        "strict": True,
        "valid": True,
        "fingerprint": FINGERPRINT,
    })
    write_json(soak / "soak.json", {
        "evidence_class": "controlled",
        "verdict": "soak_pass",
        "mechanics_pass": True,
        "duration_seconds": duration,
        "events": {
            "host": {
                "strict": True,
                "valid": True,
                "fingerprint": FINGERPRINT,
            }
        },
    })
    return benchmark, soak


class RCSoakTests(unittest.TestCase):
    def test_valid_two_hour_soak_links_to_benchmark(self):
        with tempfile.TemporaryDirectory() as tmp:
            benchmark, soak = fixture(Path(tmp))
            result = evaluate_link(benchmark, soak)
            self.assertTrue(result["ready"])
            self.assertTrue(result["eight_hour_recommended"])
            self.assertEqual(result["host_fingerprint"], FINGERPRINT)

    def test_eight_hour_soak_clears_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            benchmark, soak = fixture(Path(tmp), duration=28801)
            result = evaluate_link(benchmark, soak)
            self.assertFalse(result["eight_hour_recommended"])

    def test_short_soak_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            benchmark, soak = fixture(Path(tmp), duration=7199)
            with self.assertRaisesRegex(RCSoakError, "below required"):
                evaluate_link(benchmark, soak)

    def test_source_commit_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            benchmark, soak = fixture(Path(tmp))
            manifest = json.loads((soak / "manifest.json").read_text())
            manifest["git_commit"] = "c" * 40
            write_json(soak / "manifest.json", manifest)
            with self.assertRaisesRegex(RCSoakError, "source commit"):
                evaluate_link(benchmark, soak)

    def test_raw_host_fingerprint_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            benchmark, soak = fixture(Path(tmp))
            host = json.loads((soak / "host.json").read_text())
            host["fingerprint"] = "d" * 64
            write_json(soak / "host.json", host)
            with self.assertRaisesRegex(RCSoakError, "raw host fingerprint"):
                evaluate_link(benchmark, soak)

    def test_report_host_fingerprint_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            benchmark, soak = fixture(Path(tmp))
            report = json.loads((soak / "soak.json").read_text())
            report["events"]["host"]["fingerprint"] = "e" * 64
            write_json(soak / "soak.json", report)
            with self.assertRaisesRegex(RCSoakError, "report host fingerprint"):
                evaluate_link(benchmark, soak)

    def test_string_true_is_not_strict_boolean(self):
        with tempfile.TemporaryDirectory() as tmp:
            benchmark, soak = fixture(Path(tmp))
            manifest = json.loads((soak / "manifest.json").read_text())
            manifest["strict"] = "true"
            write_json(soak / "manifest.json", manifest)
            with self.assertRaisesRegex(RCSoakError, "JSON boolean true"):
                evaluate_link(benchmark, soak)

    def test_harness_only_soak_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            benchmark, soak = fixture(Path(tmp))
            report = json.loads((soak / "soak.json").read_text())
            report["evidence_class"] = "harness_only"
            report["verdict"] = "inconclusive"
            write_json(soak / "soak.json", report)
            with self.assertRaisesRegex(RCSoakError, "evidence_class must be controlled"):
                evaluate_link(benchmark, soak)

    def test_nginx_and_compiler_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            benchmark, soak = fixture(Path(tmp))
            manifest = json.loads((soak / "manifest.json").read_text())
            manifest["build_cc"] = "clang"
            write_json(soak / "manifest.json", manifest)
            with self.assertRaisesRegex(RCSoakError, "compiler"):
                evaluate_link(benchmark, soak)


if __name__ == "__main__":
    unittest.main()
