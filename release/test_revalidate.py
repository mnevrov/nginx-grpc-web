#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collect import EvidenceInputError
from revalidate import _assert_json_equal, revalidate_controlled, revalidate_soak


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class RevalidationTests(unittest.TestCase):
    def test_semantically_equal_json_ignores_formatting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a.json"
            b = root / "b.json"
            a.write_text('{"a": 1, "b": [2, 3]}\n', encoding="utf-8")
            b.write_text('{\n  "b": [2, 3],\n  "a": 1.0\n}\n', encoding="utf-8")
            _assert_json_equal(a, b, "fixture")

    def test_semantic_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a.json"
            b = root / "b.json"
            write_json(a, {"verdict": "pass"})
            write_json(b, {"verdict": "fail"})
            with self.assertRaisesRegex(EvidenceInputError, "does not match recomputed raw evidence"):
                _assert_json_equal(a, b, "fixture")

    def test_controlled_requires_raw_repeat_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            controlled = root / "controlled"
            controlled.mkdir()
            write_json(controlled / "manifest.json", {
                "frontend": "tls-h2",
                "transport": "text",
                "payload_bytes": 4096,
                "messages": 20,
                "backend_delay_ms": 20,
                "consumer_delay_ms": 0,
                "gateway_cpuset": "2-5",
            })
            write_json(controlled / "slo.json", {"max_error_rate": 0.01})
            write_json(controlled / "decision-policy.json", {"min_repeats": 3})
            with self.assertRaisesRegex(EvidenceInputError, "no repeat-\\* directories"):
                revalidate_controlled(root, controlled)

    def test_soak_revalidation_requires_strict_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            soak = root / "soak"
            soak.mkdir()
            write_json(soak / "manifest.json", {"strict": False})
            with self.assertRaisesRegex(EvidenceInputError, "requires strict=true"):
                revalidate_soak(root, soak)


if __name__ == "__main__":
    unittest.main()
