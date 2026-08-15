#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FINGERPRINT_FIELDS = (
    "kernel",
    "machine",
    "cpu_model",
    "online_cpus",
    "memory_bytes",
    "docker_version",
    "cgroup_version",
    "gateway_cpuset",
    "backend_cpuset",
    "cpu_governors",
)


def parse_cpuset(value: str) -> set[int]:
    result: set[int] = set()
    value = value.strip()
    if not value:
        return result
    for part in value.split(","):
        part = part.strip()
        if not part:
            raise ValueError("empty CPU-set component")
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if lo < 0 or hi < lo:
                raise ValueError(f"invalid CPU range: {part}")
            result.update(range(lo, hi + 1))
        else:
            cpu = int(part)
            if cpu < 0:
                raise ValueError(f"invalid CPU: {part}")
            result.add(cpu)
    return result


def build_fingerprint(info: dict[str, Any]) -> str:
    stable = {key: info.get(key) for key in FINGERPRINT_FIELDS}
    payload = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_preflight(info: dict[str, Any], *, strict: bool) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    def add(level: str, code: str, message: str) -> None:
        issues.append({"level": level, "code": code, "message": message})

    gateway = str(info.get("gateway_cpuset", "") or "")
    backend = str(info.get("backend_cpuset", "") or "")
    if strict and not gateway:
        add("error", "gateway_cpuset_missing", "controlled benchmark requires PERF_GATEWAY_CPUSET")
    if strict and not backend:
        add("error", "backend_cpuset_missing", "controlled benchmark requires PERF_BACKEND_CPUSET")

    try:
        gateway_cpus = parse_cpuset(gateway)
        backend_cpus = parse_cpuset(backend)
    except ValueError as exc:
        add("error", "cpuset_invalid", str(exc))
        gateway_cpus, backend_cpus = set(), set()

    overlap = gateway_cpus & backend_cpus
    if overlap:
        add("error", "cpuset_overlap", f"gateway/backend CPU sets overlap: {sorted(overlap)}")

    if str(info.get("cgroup_version", "")) != "2":
        add("error" if strict else "warning", "cgroup_v2_required", "cgroup v2 is required for release-quality CPU sampling")

    governors = [str(v) for v in info.get("cpu_governors", []) if str(v)]
    if governors and any(value != "performance" for value in governors):
        add("warning", "cpu_governor", f"CPU governors are not uniformly performance: {sorted(set(governors))}")
    if strict and not governors:
        add("warning", "cpu_governor_unknown", "CPU governor could not be determined")

    return issues


def _read_first(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return default


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def _memory_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _docker_version() -> str:
    try:
        proc = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            check=True,
            text=True,
            capture_output=True,
            timeout=10,
        )
        return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _cgroup_version() -> str:
    return "2" if Path("/sys/fs/cgroup/cgroup.controllers").exists() else "1"


def _cpu_governors() -> list[str]:
    values = {
        _read_first(path)
        for path in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_governor")
    }
    values.discard("")
    return sorted(values)


def collect_host_info(*, gateway_cpuset: str, backend_cpuset: str, strict: bool) -> dict[str, Any]:
    info: dict[str, Any] = {
        "version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "kernel": platform.release(),
        "machine": platform.machine(),
        "cpu_model": _cpu_model(),
        "online_cpus": _read_first(Path("/sys/devices/system/cpu/online"), str(os.cpu_count() or 0)),
        "memory_bytes": _memory_bytes(),
        "docker_version": _docker_version(),
        "cgroup_version": _cgroup_version(),
        "gateway_cpuset": gateway_cpuset,
        "backend_cpuset": backend_cpuset,
        "cpu_governors": _cpu_governors(),
        "strict": strict,
    }
    info["fingerprint"] = build_fingerprint(info)
    info["issues"] = validate_preflight(info, strict=strict)
    info["valid"] = not any(item["level"] == "error" for item in info["issues"])
    return info


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--gateway-cpuset", default=os.environ.get("PERF_GATEWAY_CPUSET", ""))
    parser.add_argument("--backend-cpuset", default=os.environ.get("PERF_BACKEND_CPUSET", ""))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    result = collect_host_info(
        gateway_cpuset=args.gateway_cpuset,
        backend_cpuset=args.backend_cpuset,
        strict=args.strict,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    for issue in result["issues"]:
        print(f"preflight {issue['level']}: {issue['code']}: {issue['message']}")
    if args.strict and not result["valid"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
