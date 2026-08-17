#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


class RCSoakError(ValueError):
    pass


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise RCSoakError(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RCSoakError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RCSoakError(f"{label} must be a JSON object: {path}")
    return value


def required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RCSoakError(f"{label} must be a non-empty string")
    return value.strip()


def required_true(value: Any, label: str) -> None:
    if value is not True:
        raise RCSoakError(f"{label} must be JSON boolean true")


def duration_seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RCSoakError("soak.duration_seconds must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise RCSoakError("soak.duration_seconds must be a finite non-negative number")
    return result


def evaluate_link(benchmark_manifest_path: Path, soak_dir: Path, *, min_duration_seconds: float = 7200.0) -> dict[str, Any]:
    if not math.isfinite(min_duration_seconds) or min_duration_seconds <= 0:
        raise RCSoakError("min_duration_seconds must be finite and > 0")

    benchmark = load_json(benchmark_manifest_path, "RC benchmark manifest")
    soak_manifest = load_json(soak_dir / "manifest.json", "soak manifest")
    soak_report = load_json(soak_dir / "soak.json", "soak report")
    raw_host = load_json(soak_dir / "host.json", "soak host")

    source_commit = required_string(benchmark.get("git_commit"), "benchmark.git_commit")
    nginx_version = required_string(benchmark.get("nginx_version"), "benchmark.nginx_version")
    compiler = required_string(benchmark.get("build_cc"), "benchmark.build_cc")
    benchmark_fingerprint = required_string(benchmark.get("host_fingerprint"), "benchmark.host_fingerprint")

    if required_string(soak_manifest.get("git_commit"), "soak manifest git_commit") != source_commit:
        raise RCSoakError("soak source commit does not match RC benchmark")
    if required_string(soak_manifest.get("nginx_version"), "soak manifest nginx_version") != nginx_version:
        raise RCSoakError("soak NGINX version does not match RC benchmark")
    if required_string(soak_manifest.get("build_cc"), "soak manifest build_cc") != compiler:
        raise RCSoakError("soak compiler does not match RC benchmark")
    required_true(soak_manifest.get("strict"), "soak manifest strict")

    required_true(raw_host.get("strict"), "soak raw host strict")
    required_true(raw_host.get("valid"), "soak raw host valid")
    raw_fingerprint = required_string(raw_host.get("fingerprint"), "soak raw host fingerprint")
    if raw_fingerprint != benchmark_fingerprint:
        raise RCSoakError("soak raw host fingerprint does not match RC benchmark")

    if soak_report.get("evidence_class") != "controlled":
        raise RCSoakError("soak evidence_class must be controlled")
    if soak_report.get("verdict") != "soak_pass":
        raise RCSoakError("soak verdict must be soak_pass")
    if soak_report.get("mechanics_pass") is not True:
        raise RCSoakError("soak mechanics_pass must be true")

    events = soak_report.get("events")
    if not isinstance(events, dict):
        raise RCSoakError("soak events must be an object")
    event_host = events.get("host")
    if not isinstance(event_host, dict):
        raise RCSoakError("soak events.host must be an object")
    required_true(event_host.get("strict"), "soak events.host.strict")
    required_true(event_host.get("valid"), "soak events.host.valid")
    event_fingerprint = required_string(event_host.get("fingerprint"), "soak events.host.fingerprint")
    if event_fingerprint != benchmark_fingerprint:
        raise RCSoakError("soak report host fingerprint does not match RC benchmark")

    duration = duration_seconds(soak_report.get("duration_seconds"))
    if duration < min_duration_seconds:
        raise RCSoakError(
            f"strict soak duration {duration:.1f}s is below required {min_duration_seconds:.1f}s"
        )

    return {
        "version": 1,
        "ready": True,
        "source_commit": source_commit,
        "nginx_version": nginx_version,
        "compiler": compiler,
        "host_fingerprint": benchmark_fingerprint,
        "duration_seconds": duration,
        "minimum_duration_seconds": float(min_duration_seconds),
        "eight_hour_recommended": duration < 28800.0,
        "soak_verdict": "soak_pass",
    }


def render_markdown(result: dict[str, Any]) -> str:
    return "\n".join([
        "# M15 RC soak linkage",
        "",
        f"Source: `{result['source_commit']}`  ",
        f"NGINX/compiler: `{result['nginx_version']}` / `{result['compiler']}`  ",
        f"Host fingerprint: `{result['host_fingerprint']}`  ",
        f"Duration: `{result['duration_seconds']:.1f}` s  ",
        f"Minimum: `{result['minimum_duration_seconds']:.1f}` s  ",
        f"Verdict: **`{result['soak_verdict']}`**",
        "",
        f"8-hour RC soak still recommended: `{str(result['eight_hour_recommended']).lower()}`",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-manifest", required=True, type=Path)
    parser.add_argument("--soak-dir", required=True, type=Path)
    parser.add_argument("--min-duration-seconds", type=float, default=7200.0)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown", required=True, type=Path)
    args = parser.parse_args()

    try:
        result = evaluate_link(
            args.benchmark_manifest,
            args.soak_dir,
            min_duration_seconds=args.min_duration_seconds,
        )
    except (RCSoakError, ValueError) as exc:
        print(f"RC soak linkage error: {exc}")
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
