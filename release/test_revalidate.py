#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collect import EvidenceInputError
from revalidate import _assert_json_equal, _validate_controlled_host, revalidate_controlled, revalidate_soak


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def controlled_fixture(root: Path, **overrides) -> Path:
    controlled = root / "controlled"
    controlled.mkdir()
    manifest = {
        "frontend": "tls-h2",
        "transport": "text",
        "payload_bytes": 4096,
        "messages": 20,
        "backend_delay_ms": 20,
        "consumer_delay_ms": 0,
        "gateway_cpuset": "2-5",
        "strict_preflight": True,
    }
    manifest.update(overrides)
    write_json(controlled / "manifest.json", manifest)
    write_json(controlled / "slo.json", {"max_error_rate": 0.01})
    write_json(controlled / "decision-policy.json", {"min_repeats": 3})
    return controlled


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
            controlled = controlled_fixture(root)
            with self.assertRaisesRegex(EvidenceInputError, "no repeat-\\* directories"):
                revalidate_controlled(root, controlled)

    def test_controlled_rejects_string_integer_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            controlled = controlled_fixture(root, messages="20")
            with self.assertRaisesRegex(EvidenceInputError, "messages must be an integer"):
                revalidate_controlled(root, controlled)

    def test_controlled_rejects_boolean_integer_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            controlled = controlled_fixture(root, payload_bytes=True)
            with self.assertRaisesRegex(EvidenceInputError, "payload_bytes must be an integer"):
                revalidate_controlled(root, controlled)

    def test_controlled_requires_boolean_true_manifest_preflight(self):
        for value in (False, "true", "false", 1, 0, None):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                controlled = controlled_fixture(root, strict_preflight=value)
                with self.assertRaisesRegex(EvidenceInputError, "strict_preflight=true boolean"):
                    revalidate_controlled(root, controlled)

    def test_controlled_host_flags_require_exact_boolean_true(self):
        invalid_values = (False, "true", "false", 1, 0, None)
        for field in ("strict", "valid"):
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    host = {"strict": True, "valid": True, "fingerprint": "host-a"}
                    if value is None:
                        del host[field]
                    else:
                        host[field] = value
                    with self.assertRaisesRegex(EvidenceInputError, rf"{field} must be boolean true"):
                        _validate_controlled_host(host, "controlled host repeat-01")

    def test_controlled_host_requires_non_empty_fingerprint(self):
        for value in (None, "", "   ", 123):
            with self.subTest(value=value):
                host = {"strict": True, "valid": True, "fingerprint": value}
                with self.assertRaisesRegex(EvidenceInputError, "fingerprint must be a non-empty string"):
                    _validate_controlled_host(host, "controlled host repeat-01")

    def test_controlled_host_accepts_exact_strict_valid_booleans(self):
        _validate_controlled_host(
            {"strict": True, "valid": True, "fingerprint": "host-a"},
            "controlled host repeat-01",
        )

    def test_soak_revalidation_requires_strict_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            soak = root / "soak"
            soak.mkdir()
            write_json(soak / "manifest.json", {"strict": False})
            with self.assertRaisesRegex(EvidenceInputError, "requires strict=true"):
                revalidate_soak(root, soak)

    def test_soak_revalidation_rejects_string_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            soak = root / "soak"
            soak.mkdir()
            write_json(soak / "manifest.json", {"strict": "true"})
            with self.assertRaisesRegex(EvidenceInputError, "requires strict=true boolean"):
                revalidate_soak(root, soak)


if __name__ == "__main__":
    unittest.main()
