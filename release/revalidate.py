#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from collect import EvidenceInputError, load_json


def _run(args: list[str]) -> None:
    try:
        subprocess.run(args, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvidenceInputError(f"evidence revalidation command failed: {' '.join(args)}: {exc}") from exc


def _assert_json_equal(expected_path: Path, actual_path: Path, label: str) -> None:
    expected = load_json(expected_path, f"original {label}")
    actual = load_json(actual_path, f"revalidated {label}")
    if expected != actual:
        raise EvidenceInputError(f"{label} does not match recomputed raw evidence")


def revalidate_controlled(repo_root: Path, controlled_dir: Path) -> dict[str, Any]:
    manifest = load_json(controlled_dir / "manifest.json", "controlled manifest")
    slo_path = controlled_dir / "slo.json"
    policy_path = controlled_dir / "decision-policy.json"
    if not slo_path.is_file():
        raise EvidenceInputError(f"missing controlled SLO: {slo_path}")
    if not policy_path.is_file():
        raise EvidenceInputError(f"missing controlled decision policy: {policy_path}")

    frontend = str(manifest.get("frontend", ""))
    transport = str(manifest.get("transport", ""))
    payload_bytes = int(manifest.get("payload_bytes", 0) or 0)
    messages = int(manifest.get("messages", 0) or 0)
    backend_delay_ms = int(manifest.get("backend_delay_ms", 0) or 0)
    consumer_delay_ms = int(manifest.get("consumer_delay_ms", 0) or 0)
    gateway_cpuset = str(manifest.get("gateway_cpuset", "") or "")
    if frontend not in {"http1", "tls-h2"}:
        raise EvidenceInputError(f"invalid controlled frontend in manifest: {frontend!r}")
    if transport not in {"text", "binary"}:
        raise EvidenceInputError(f"invalid controlled transport in manifest: {transport!r}")
    if payload_bytes < 0 or messages <= 0 or backend_delay_ms < 0 or consumer_delay_ms < 0:
        raise EvidenceInputError("invalid controlled scenario values in manifest")

    repeats = sorted(path for path in controlled_dir.glob("repeat-*") if path.is_dir())
    if not repeats:
        raise EvidenceInputError("controlled evidence has no repeat-* directories")

    capacity_script = repo_root / "perf" / "capacity.py"
    for repeat in repeats:
        report = repeat / "report.json"
        original = repeat / "capacity.json"
        revalidated = repeat / "capacity.revalidated.json"
        if not report.is_file():
            raise EvidenceInputError(f"missing controlled raw report: {report}")
        args = [
            sys.executable,
            str(capacity_script),
            "--report", str(report),
            "--slo", str(slo_path),
            "--output", str(revalidated),
            "--frontend", frontend,
            "--transport", transport,
            "--payload-bytes", str(payload_bytes),
            "--messages", str(messages),
            "--delay-ms", str(backend_delay_ms),
            "--consumer-delay-ms", str(consumer_delay_ms),
        ]
        if gateway_cpuset:
            args.extend(["--gateway-cpuset", gateway_cpuset])
        _run(args)
        _assert_json_equal(original, revalidated, f"capacity result {repeat.name}")

    decision_revalidated = controlled_dir / "decision.revalidated.json"
    decision_md = controlled_dir / "decision.revalidated.md"
    _run([
        sys.executable,
        str(repo_root / "perf" / "decision.py"),
        "--input", str(controlled_dir),
        "--policy", str(policy_path),
        "--output", str(decision_revalidated),
        "--markdown", str(decision_md),
    ])
    _assert_json_equal(controlled_dir / "decision.json", decision_revalidated, "controlled decision")
    return {"repeats": len(repeats), "decision_revalidated": True}


def revalidate_soak(repo_root: Path, soak_dir: Path) -> dict[str, Any]:
    manifest = load_json(soak_dir / "manifest.json", "soak manifest")
    if not bool(manifest.get("strict")):
        raise EvidenceInputError("production soak revalidation requires strict=true")

    stats = soak_dir / "nginx.stats.tsv"
    events = soak_dir / "events.json"
    policy = soak_dir / "soak-policy.json"
    for path, label in ((stats, "soak stats"), (events, "soak events"), (policy, "soak policy")):
        if not path.is_file():
            raise EvidenceInputError(f"missing {label}: {path}")

    revalidated = soak_dir / "soak.revalidated.json"
    markdown = soak_dir / "soak.revalidated.md"
    _run([
        sys.executable,
        str(repo_root / "perf" / "soak.py"),
        "--stats", str(stats),
        "--events", str(events),
        "--policy", str(policy),
        "--output", str(revalidated),
        "--markdown", str(markdown),
        "--container", "native-nginx",
        "--strict",
    ])
    _assert_json_equal(soak_dir / "soak.json", revalidated, "soak result")
    result = load_json(revalidated, "revalidated soak result")
    return {
        "duration_seconds": float(result.get("duration_seconds", 0.0) or 0.0),
        "soak_revalidated": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--controlled-dir", required=True, type=Path)
    parser.add_argument("--soak-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        result = {
            "version": 1,
            "controlled": revalidate_controlled(args.repo_root, args.controlled_dir),
            "soak": revalidate_soak(args.repo_root, args.soak_dir),
        }
    except (EvidenceInputError, ValueError) as exc:
        result = {"version": 1, "valid": False, "reason": "raw_revalidation", "error": str(exc)}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 1

    result["valid"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
