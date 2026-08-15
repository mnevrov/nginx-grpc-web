#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


class EvidenceInputError(ValueError):
    pass


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise EvidenceInputError(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceInputError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceInputError(f"{label} must contain a JSON object: {path}")
    return value


def parse_manifest(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise EvidenceInputError(f"missing artifact manifest: {path}")
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise EvidenceInputError(f"cannot read artifact manifest: {path}: {exc}") from exc
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line == "Compatibility contract:":
            break
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            result[key] = value.strip()
    required = {"module", "nginx_version", "compiler", "platform", "build_mode", "source_commit"}
    missing = sorted(required - set(result))
    if missing:
        raise EvidenceInputError(f"artifact manifest missing fields: {', '.join(missing)}")
    return result


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise EvidenceInputError(f"missing module artifact: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise EvidenceInputError(f"cannot hash module artifact: {path}: {exc}") from exc
    return digest.hexdigest()


def declared_sha256(path: Path, module_name: str) -> str:
    if not path.is_file():
        raise EvidenceInputError(f"missing checksum file: {path}")
    matches: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise EvidenceInputError(f"cannot read checksum file: {path}: {exc}") from exc
    for line in lines:
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        filename = parts[-1].lstrip("*")
        if Path(filename).name == module_name:
            matches.append(parts[0].lower())
    if len(matches) != 1:
        raise EvidenceInputError(f"expected exactly one checksum for {module_name}, found {len(matches)}")
    return matches[0]


def git_source(repo_root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=normal"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvidenceInputError(f"cannot determine git source provenance: {exc}") from exc
    if not commit:
        raise EvidenceInputError("git returned an empty source commit")
    return {"commit": commit, "dirty": bool(status.strip())}


def collect_bundle(
    *,
    release_version: str,
    source: dict[str, Any],
    gates_path: Path,
    package_dir: Path,
    controlled_dir: Path,
    soak_dir: Path,
) -> dict[str, Any]:
    gates = load_json(gates_path, "release gates")
    module_name = "ngx_http_grpc_web_module.so"
    manifest = parse_manifest(package_dir / "MANIFEST.txt")
    if manifest.get("module") != module_name:
        raise EvidenceInputError(f"artifact manifest module must be {module_name}")

    return {
        "release_version": release_version,
        "source": dict(source),
        "gates": gates,
        "artifact": {
            "declared_sha256": declared_sha256(package_dir / "SHA256SUMS", module_name),
            "actual_sha256": sha256_file(package_dir / module_name),
            "manifest": manifest,
        },
        "controlled": {
            "manifest": load_json(controlled_dir / "manifest.json", "controlled manifest"),
            "decision": load_json(controlled_dir / "decision.json", "controlled decision"),
        },
        "soak": {
            "manifest": load_json(soak_dir / "manifest.json", "soak manifest"),
            "report": load_json(soak_dir / "soak.json", "soak report"),
        },
    }
