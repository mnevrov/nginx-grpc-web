#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from collect import EvidenceInputError, collect_bundle, declared_sha256, parse_manifest, sha256_file


COMMIT = "a" * 40


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def create_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    package = root / "package"
    controlled = root / "controlled"
    soak = root / "soak"
    package.mkdir()
    controlled.mkdir()
    soak.mkdir()

    module = package / "ngx_http_grpc_web_module.so"
    module.write_bytes(b"fake-module\x00payload")
    digest = hashlib.sha256(module.read_bytes()).hexdigest()
    (package / "SHA256SUMS").write_text(f"{digest}  ngx_http_grpc_web_module.so\n", encoding="utf-8")
    (package / "MANIFEST.txt").write_text(
        "\n".join([
            "module=ngx_http_grpc_web_module.so",
            "nginx_version=1.30.4",
            "compiler=gcc",
            "platform=linux-x86_64",
            "build_mode=--with-compat",
            f"source_commit={COMMIT}",
            "",
            "Compatibility contract:",
            "- fixture",
            "",
        ]),
        encoding="utf-8",
    )

    gates_path = root / "gates.json"
    write_json(gates_path, {
        "protocol": {"passed": True, "commit": COMMIT},
        "differential": {"passed": True, "commit": COMMIT},
        "browser": {"passed": True, "commit": COMMIT},
        "hardening": {"passed": True, "commit": COMMIT},
    })
    write_json(controlled / "manifest.json", {
        "git_commit": COMMIT,
        "nginx_version": "1.30.4",
        "build_cc": "gcc",
    })
    write_json(controlled / "decision.json", {
        "evidence_class": "controlled",
        "recommendation": "native_preferred",
        "host_fingerprint": "host-a",
    })
    write_json(soak / "manifest.json", {
        "git_commit": COMMIT,
        "strict": True,
        "nginx_version": "1.30.4",
        "build_cc": "gcc",
    })
    write_json(soak / "soak.json", {
        "evidence_class": "controlled",
        "verdict": "soak_pass",
        "duration_seconds": 7201,
        "events": {"host": {"strict": True, "valid": True, "fingerprint": "host-a"}},
    })
    return gates_path, package, controlled, soak


class CollectorTests(unittest.TestCase):
    def test_collect_recalculates_module_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gates, package, controlled, soak = create_fixture(root)
            bundle = collect_bundle(
                release_version="v0.1.0",
                source={"commit": COMMIT, "dirty": False},
                gates_path=gates,
                package_dir=package,
                controlled_dir=controlled,
                soak_dir=soak,
            )
            self.assertEqual(bundle["artifact"]["declared_sha256"], bundle["artifact"]["actual_sha256"])
            self.assertEqual(bundle["artifact"]["manifest"]["source_commit"], COMMIT)

    def test_tampered_artifact_preserves_checksum_mismatch_for_evaluator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gates, package, controlled, soak = create_fixture(root)
            (package / "ngx_http_grpc_web_module.so").write_bytes(b"tampered")
            bundle = collect_bundle(
                release_version="v0.1.0",
                source={"commit": COMMIT, "dirty": False},
                gates_path=gates,
                package_dir=package,
                controlled_dir=controlled,
                soak_dir=soak,
            )
            self.assertNotEqual(bundle["artifact"]["declared_sha256"], bundle["artifact"]["actual_sha256"])

    def test_missing_manifest_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, package, _, _ = create_fixture(root)
            text = (package / "MANIFEST.txt").read_text(encoding="utf-8")
            (package / "MANIFEST.txt").write_text(text.replace("build_mode=--with-compat\n", ""), encoding="utf-8")
            with self.assertRaisesRegex(EvidenceInputError, "artifact manifest missing fields: build_mode"):
                parse_manifest(package / "MANIFEST.txt")

    def test_invalid_controlled_json_is_rejected_with_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gates, package, controlled, soak = create_fixture(root)
            (controlled / "decision.json").write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(EvidenceInputError, "invalid controlled decision"):
                collect_bundle(
                    release_version="v0.1.0",
                    source={"commit": COMMIT, "dirty": False},
                    gates_path=gates,
                    package_dir=package,
                    controlled_dir=controlled,
                    soak_dir=soak,
                )

    def test_checksum_file_requires_exactly_one_module_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "SHA256SUMS"
            path.write_text("a" * 64 + "  other.so\n", encoding="utf-8")
            with self.assertRaisesRegex(EvidenceInputError, "expected exactly one checksum"):
                declared_sha256(path, "ngx_http_grpc_web_module.so")

    def test_sha256_file_matches_hashlib(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "module.so"
            data = b"abc123"
            path.write_bytes(data)
            self.assertEqual(sha256_file(path), hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    unittest.main()
