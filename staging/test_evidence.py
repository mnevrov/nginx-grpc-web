#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from evidence import StagingEvidenceError, evaluate


COMMIT = "a" * 40


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def fixture(root: Path) -> dict[str, Path]:
    package = root / "package"
    package.mkdir()
    module = package / "ngx_http_grpc_web_module.so"
    module.write_bytes(b"staging-module-fixture")
    digest = hashlib.sha256(module.read_bytes()).hexdigest()
    (package / "SHA256SUMS").write_text(f"{digest}  ngx_http_grpc_web_module.so\n", encoding="utf-8")
    (package / "MANIFEST.txt").write_text("\n".join([
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
    ]), encoding="utf-8")

    endpoints = {
        "staging_endpoint": "https://staging.example/grpc-web",
        "staging_unavailable_endpoint": "https://staging.example/grpc-web-unavailable",
        "staging_timeout_endpoint": "https://staging.example/grpc-web-timeout",
    }
    native = root / "native-browser"
    rollback = root / "rollback-browser"
    write_json(native / "manifest.json", {
        "git_commit": COMMIT,
        "label": "native-module",
        "browser": "chromium",
        "endpoints": endpoints,
        "playwright_exit_code": 0,
        "browser_acceptance_passed": True,
    })
    write_json(rollback / "manifest.json", {
        "git_commit": COMMIT,
        "label": "envoy-rollback",
        "browser": "chromium",
        "endpoints": endpoints,
        "playwright_exit_code": 0,
        "browser_acceptance_passed": True,
    })

    nginx_v = root / "nginx-V.txt"
    nginx_v.write_text("nginx version: nginx/1.30.4\nbuilt by gcc\n", encoding="utf-8")
    nginx_t = root / "nginx-T.txt"
    nginx_t.write_text("load_module modules/ngx_http_grpc_web_module.so;\n", encoding="utf-8")
    deployed = root / "deployed-module.sha256"
    deployed.write_text(f"{digest}  /usr/lib/nginx/modules/ngx_http_grpc_web_module.so\n", encoding="utf-8")
    rss = root / "rss.txt"
    rss.write_text("master pid stable; worker RSS before=32MiB peak=35MiB after=32MiB; restart_count=0\n", encoding="utf-8")
    rollback_log = root / "rollback.txt"
    rollback_log.write_text("2026-08-17T12:00:00Z weighted pool switched from native module to Envoy; health green\n", encoding="utf-8")

    return {
        "package": package,
        "native": native,
        "rollback": rollback,
        "nginx_v": nginx_v,
        "nginx_t": nginx_t,
        "deployed": deployed,
        "rss": rss,
        "rollback_log": rollback_log,
    }


def evaluate_fixture(paths: dict[str, Path], *, source_commit: str = COMMIT):
    return evaluate(
        source_commit=source_commit,
        package_dir=paths["package"],
        native_browser_dir=paths["native"],
        rollback_browser_dir=paths["rollback"],
        nginx_v_path=paths["nginx_v"],
        nginx_t_path=paths["nginx_t"],
        deployed_sha256_path=paths["deployed"],
        rss_evidence_path=paths["rss"],
        rollback_evidence_path=paths["rollback_log"],
    )


class StagingEvidenceTests(unittest.TestCase):
    def test_valid_staging_and_rollback_evidence_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_fixture(fixture(Path(tmp)))
            self.assertEqual(result["verdict"], "staging_pass")
            self.assertTrue(result["native_browser"]["passed"])
            self.assertTrue(result["envoy_rollback_browser"]["passed"])

    def test_deployed_checksum_must_match_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = fixture(Path(tmp))
            paths["deployed"].write_text("c" * 64 + "  module.so\n", encoding="utf-8")
            with self.assertRaisesRegex(StagingEvidenceError, "deployed module checksum"):
                evaluate_fixture(paths)

    def test_native_browser_failure_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = fixture(Path(tmp))
            manifest_path = paths["native"] / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["browser_acceptance_passed"] = False
            manifest["playwright_exit_code"] = 1
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(StagingEvidenceError, "native browser acceptance"):
                evaluate_fixture(paths)

    def test_rollback_must_keep_same_external_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = fixture(Path(tmp))
            manifest_path = paths["rollback"] / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["endpoints"]["staging_endpoint"] = "https://different.example/grpc-web"
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(StagingEvidenceError, "external staging endpoints changed"):
                evaluate_fixture(paths)

    def test_nginx_t_must_reference_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = fixture(Path(tmp))
            paths["nginx_t"].write_text("events {}\nhttp {}\n", encoding="utf-8")
            with self.assertRaisesRegex(StagingEvidenceError, "does not reference"):
                evaluate_fixture(paths)

    def test_browser_source_commit_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = fixture(Path(tmp))
            manifest_path = paths["rollback"] / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["git_commit"] = "d" * 40
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(StagingEvidenceError, "rollback browser source commit"):
                evaluate_fixture(paths)

    def test_empty_rollback_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = fixture(Path(tmp))
            paths["rollback_log"].write_text("", encoding="utf-8")
            with self.assertRaisesRegex(StagingEvidenceError, "must not be empty"):
                evaluate_fixture(paths)

    def test_package_source_commit_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = fixture(Path(tmp))
            with self.assertRaisesRegex(StagingEvidenceError, "package source commit"):
                evaluate_fixture(paths, source_commit="e" * 40)


if __name__ == "__main__":
    unittest.main()
