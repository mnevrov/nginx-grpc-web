#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "release"))
from collect import EvidenceInputError, declared_sha256, parse_manifest, sha256_file  # noqa: E402


class StagingEvidenceError(ValueError):
    pass


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise StagingEvidenceError(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StagingEvidenceError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StagingEvidenceError(f"{label} must be a JSON object: {path}")
    return value


def non_empty_text(path: Path, label: str) -> str:
    if not path.is_file():
        raise StagingEvidenceError(f"missing {label}: {path}")
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise StagingEvidenceError(f"cannot read {label}: {path}: {exc}") from exc
    if not text:
        raise StagingEvidenceError(f"{label} must not be empty: {path}")
    return text


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_deployed_sha256(path: Path) -> str:
    text = non_empty_text(path, "deployed module checksum")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise StagingEvidenceError("deployed module checksum file must contain exactly one non-empty line")
    parts = lines[0].split()
    if not parts:
        raise StagingEvidenceError("deployed module checksum line is empty")
    digest = parts[0].lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise StagingEvidenceError("deployed module checksum is not a SHA256 digest")
    return digest


def validate_browser(manifest: dict[str, Any], label: str, source_commit: str) -> dict[str, str]:
    if manifest.get("git_commit") != source_commit:
        raise StagingEvidenceError(f"{label} browser source commit does not match release source")
    if manifest.get("browser_acceptance_passed") is not True:
        raise StagingEvidenceError(f"{label} browser acceptance did not pass")
    exit_code = manifest.get("playwright_exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int) or exit_code != 0:
        raise StagingEvidenceError(f"{label} Playwright exit code must be integer 0")
    endpoints = manifest.get("endpoints")
    if not isinstance(endpoints, dict):
        raise StagingEvidenceError(f"{label} browser endpoints must be an object")
    required = ("staging_endpoint", "staging_unavailable_endpoint", "staging_timeout_endpoint")
    result: dict[str, str] = {}
    for name in required:
        value = endpoints.get(name)
        if not isinstance(value, str) or not value.strip():
            raise StagingEvidenceError(f"{label} browser endpoint {name} must be non-empty")
        result[name] = value.strip()
    return result


def evaluate(
    *,
    source_commit: str,
    package_dir: Path,
    native_browser_dir: Path,
    rollback_browser_dir: Path,
    nginx_v_path: Path,
    nginx_t_path: Path,
    deployed_sha256_path: Path,
    rss_evidence_path: Path,
    rollback_evidence_path: Path,
) -> dict[str, Any]:
    if not source_commit.strip():
        raise StagingEvidenceError("source_commit must be non-empty")

    try:
        package_manifest = parse_manifest(package_dir / "MANIFEST.txt")
        module_name = package_manifest["module"]
        actual_package_sha = sha256_file(package_dir / module_name)
        declared_package_sha = declared_sha256(package_dir / "SHA256SUMS", module_name)
    except EvidenceInputError as exc:
        raise StagingEvidenceError(str(exc)) from exc

    if module_name != "ngx_http_grpc_web_module.so":
        raise StagingEvidenceError("unexpected module name in package manifest")
    if package_manifest.get("source_commit") != source_commit:
        raise StagingEvidenceError("package source commit does not match staging source")
    if actual_package_sha != declared_package_sha:
        raise StagingEvidenceError("package module checksum does not match SHA256SUMS")

    deployed_sha = parse_deployed_sha256(deployed_sha256_path)
    if deployed_sha != actual_package_sha:
        raise StagingEvidenceError("deployed module checksum does not match exact-commit package")

    if native_browser_dir.resolve() == rollback_browser_dir.resolve():
        raise StagingEvidenceError("native and Envoy rollback browser evidence must come from distinct directories")

    native = load_json(native_browser_dir / "manifest.json", "native browser manifest")
    rollback = load_json(rollback_browser_dir / "manifest.json", "rollback browser manifest")
    if native.get("label") != "native-module":
        raise StagingEvidenceError("native browser manifest label must be 'native-module'")
    if rollback.get("label") != "envoy-rollback":
        raise StagingEvidenceError("rollback browser manifest label must be 'envoy-rollback'")
    native_endpoints = validate_browser(native, "native", source_commit)
    rollback_endpoints = validate_browser(rollback, "rollback", source_commit)
    if native_endpoints != rollback_endpoints:
        raise StagingEvidenceError("external staging endpoints changed between native and Envoy rollback runs")

    nginx_v = non_empty_text(nginx_v_path, "nginx -V evidence")
    nginx_t = non_empty_text(nginx_t_path, "nginx -T evidence")
    rss_text = non_empty_text(rss_evidence_path, "staging RSS observation")
    rollback_text = non_empty_text(rollback_evidence_path, "Envoy rollback evidence")

    nginx_version = package_manifest.get("nginx_version", "")
    if nginx_version and f"nginx/{nginx_version}" not in nginx_v:
        raise StagingEvidenceError(f"nginx -V evidence does not identify nginx/{nginx_version}")
    if module_name not in nginx_t:
        raise StagingEvidenceError("nginx -T evidence does not reference the packaged module")

    return {
        "version": 1,
        "source_commit": source_commit,
        "verdict": "staging_pass",
        "package": {
            "module": module_name,
            "sha256": actual_package_sha,
            "nginx_version": package_manifest.get("nginx_version", ""),
            "compiler": package_manifest.get("compiler", ""),
        },
        "external_endpoints": native_endpoints,
        "native_browser": {
            "label": native.get("label", ""),
            "browser": native.get("browser", ""),
            "passed": True,
        },
        "envoy_rollback_browser": {
            "label": rollback.get("label", ""),
            "browser": rollback.get("browser", ""),
            "passed": True,
        },
        "evidence_sha256": {
            "nginx_v": file_sha256(nginx_v_path),
            "nginx_t": file_sha256(nginx_t_path),
            "deployed_module_sha256_file": file_sha256(deployed_sha256_path),
            "rss_observation": file_sha256(rss_evidence_path),
            "rollback": file_sha256(rollback_evidence_path),
        },
        "rss_evidence_bytes": len(rss_text.encode("utf-8")),
        "rollback_evidence_bytes": len(rollback_text.encode("utf-8")),
    }


def render_markdown(result: dict[str, Any]) -> str:
    package = result["package"]
    return "\n".join([
        "# M15 staging acceptance evidence",
        "",
        f"Source: `{result['source_commit']}`  ",
        f"Verdict: **`{result['verdict']}`**  ",
        f"Package: `{package['module']}` / `{package['sha256']}`  ",
        f"NGINX/compiler: `{package['nginx_version']}` / `{package['compiler']}`",
        "",
        "- native React/grpc-web suite: `pass`",
        "- Envoy rollback React/grpc-web suite: `pass`",
        "- external endpoint identity preserved: `true`",
        "- deployed module checksum matches package: `true`",
        "- nginx -V/-T, RSS observation and rollback evidence: preserved and hashed",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--native-browser-dir", required=True, type=Path)
    parser.add_argument("--rollback-browser-dir", required=True, type=Path)
    parser.add_argument("--nginx-v", required=True, type=Path)
    parser.add_argument("--nginx-t", required=True, type=Path)
    parser.add_argument("--deployed-sha256", required=True, type=Path)
    parser.add_argument("--rss-evidence", required=True, type=Path)
    parser.add_argument("--rollback-evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown", required=True, type=Path)
    args = parser.parse_args()

    try:
        result = evaluate(
            source_commit=args.source_commit,
            package_dir=args.package_dir,
            native_browser_dir=args.native_browser_dir,
            rollback_browser_dir=args.rollback_browser_dir,
            nginx_v_path=args.nginx_v,
            nginx_t_path=args.nginx_t,
            deployed_sha256_path=args.deployed_sha256,
            rss_evidence_path=args.rss_evidence,
            rollback_evidence_path=args.rollback_evidence,
        )
    except (StagingEvidenceError, ValueError, OSError) as exc:
        print(f"staging evidence error: {exc}")
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
