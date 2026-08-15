#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MIB = 1024.0 * 1024.0


@dataclass(frozen=True)
class SoakPolicy:
    min_duration_seconds: float = 7200.0
    min_samples: int = 240
    warmup_seconds: float = 300.0
    max_rss_slope_mib_per_hour: float = 8.0
    max_rss_growth_mib: float = 64.0
    max_peak_rss_mib: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SoakPolicy":
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"unknown soak policy fields: {', '.join(unknown)}")
        values: dict[str, Any] = {}
        for name in allowed:
            if name not in data:
                continue
            value = data[name]
            values[name] = int(value) if name == "min_samples" else (None if value is None else float(value))
        policy = cls(**values)
        policy.validate()
        return policy

    def validate(self) -> None:
        if self.min_duration_seconds <= 0:
            raise ValueError("min_duration_seconds must be > 0")
        if self.min_samples < 3:
            raise ValueError("min_samples must be >= 3")
        if self.warmup_seconds < 0 or self.warmup_seconds >= self.min_duration_seconds:
            raise ValueError("warmup_seconds must be >= 0 and smaller than min_duration_seconds")
        if self.max_rss_slope_mib_per_hour < 0 or self.max_rss_growth_mib < 0:
            raise ValueError("RSS limits must be >= 0")
        if self.max_peak_rss_mib is not None and self.max_peak_rss_mib <= 0:
            raise ValueError("max_peak_rss_mib must be > 0 when configured")


def linear_slope_per_hour(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        raise ValueError("at least two points are required for slope")
    xs = [float(x) for x, _ in points]
    ys = [float(y) for _, y in points]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    slope_per_second = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator
    return slope_per_second * 3600.0


def parse_stats(path: Path, *, container: str = "nginx") -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"timestamp", "container", "rss_bytes", "memory_current_bytes"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError("stats TSV is missing required columns")
        for row in reader:
            if row["container"] != container:
                continue
            rows.append({
                "timestamp": float(row["timestamp"]),
                "container": row["container"],
                "rss_mib": float(row["rss_bytes"]) / MIB,
                "memory_current_mib": float(row["memory_current_bytes"]) / MIB,
            })
    if not rows:
        raise ValueError(f"no stats rows for container {container!r}")
    rows.sort(key=lambda item: float(item["timestamp"]))
    first = float(rows[0]["timestamp"])
    for row in rows:
        row["timestamp"] = float(row["timestamp"]) - first
    return rows


def _event_dict(events: dict[str, Any], name: str) -> dict[str, Any]:
    value = events.get(name)
    return value if isinstance(value, dict) else {}


def _unexpected_errors(events: dict[str, Any], name: str) -> int:
    return int(_event_dict(events, name).get("unexpected_errors", 0) or 0)


def evaluate_soak(timeline: dict[str, Any], policy: SoakPolicy) -> dict[str, Any]:
    policy.validate()
    samples = sorted([dict(item) for item in timeline.get("samples", [])], key=lambda item: float(item["timestamp"]))
    events = timeline.get("events") if isinstance(timeline.get("events"), dict) else {}
    strict = bool(timeline.get("strict"))
    reasons: list[str] = []

    sample_count = len(samples)
    duration = 0.0 if sample_count < 2 else float(samples[-1]["timestamp"]) - float(samples[0]["timestamp"])
    if sample_count < policy.min_samples:
        reasons.append("samples")
    if duration < policy.min_duration_seconds:
        reasons.append("duration")

    warmup_cutoff = (float(samples[0]["timestamp"]) + policy.warmup_seconds) if samples else policy.warmup_seconds
    trend_samples = [item for item in samples if float(item["timestamp"]) >= warmup_cutoff]
    rss_slope = 0.0
    rss_growth = 0.0
    peak_rss = max((float(item["rss_mib"]) for item in samples), default=0.0)
    peak_memory_current = max((float(item.get("memory_current_mib", 0.0)) for item in samples), default=0.0)
    if len(trend_samples) >= 2:
        points = [(float(item["timestamp"]), float(item["rss_mib"])) for item in trend_samples]
        rss_slope = linear_slope_per_hour(points)
        rss_growth = float(trend_samples[-1]["rss_mib"]) - float(trend_samples[0]["rss_mib"])
        if rss_slope > policy.max_rss_slope_mib_per_hour:
            reasons.append("rss_slope")
        if rss_growth > policy.max_rss_growth_mib:
            reasons.append("rss_growth")
    else:
        reasons.append("trend_samples")
    if policy.max_peak_rss_mib is not None and peak_rss > policy.max_peak_rss_mib:
        reasons.append("peak_rss")

    host = _event_dict(events, "host")
    if strict and (not bool(host.get("strict")) or not bool(host.get("valid")) or not str(host.get("fingerprint", ""))):
        reasons.append("host_preflight")

    for phase in ("steady", "churn", "cancel"):
        if _unexpected_errors(events, phase) != 0:
            reasons.append(f"{phase}_errors")

    cancel = _event_dict(events, "cancel")
    expected_cancel = int(cancel.get("expected_cancellations", 0) or 0)
    observed_cancel = int(cancel.get("observed_cancellations", 0) or 0)
    if expected_cancel <= 0 or observed_cancel != expected_cancel:
        reasons.append("cancellation_accounting")

    backend_restart = _event_dict(events, "backend_restart")
    if int(backend_restart.get("attempted", 0) or 0) <= 0 or not bool(backend_restart.get("recovery_success")):
        reasons.append("backend_recovery")
    if not bool(backend_restart.get("observed_disruption")) or int(backend_restart.get("inflight_errors", 0) or 0) <= 0:
        reasons.append("backend_disruption")

    transport_reset = _event_dict(events, "transport_reset")
    if int(transport_reset.get("attempted", 0) or 0) <= 0 or not bool(transport_reset.get("recovery_success")):
        reasons.append("transport_recovery")
    expected_reset = int(transport_reset.get("expected_failures", 0) or 0)
    observed_reset = int(transport_reset.get("observed_failures", 0) or 0)
    if expected_reset <= 0 or observed_reset != expected_reset:
        reasons.append("transport_reset_accounting")

    if not bool(_event_dict(events, "final_probe").get("success")):
        reasons.append("final_probe")

    nginx = _event_dict(events, "nginx")
    if (
        nginx.get("master_pid_start") in (None, "")
        or nginx.get("master_pid_end") in (None, "")
        or str(nginx.get("master_pid_start")) != str(nginx.get("master_pid_end"))
        or int(nginx.get("container_restart_count_start", -1)) != int(nginx.get("container_restart_count_end", -2))
    ):
        reasons.append("nginx_restart")

    hard_reasons = list(dict.fromkeys(reasons))
    mechanics_pass = not hard_reasons
    if strict:
        evidence_class = "controlled"
        verdict = "soak_pass" if mechanics_pass else "soak_fail"
    else:
        evidence_class = "harness_only"
        hard_reasons.append("harness_only")
        verdict = "inconclusive"

    return {
        "version": 1,
        "evidence_class": evidence_class,
        "verdict": verdict,
        "mechanics_pass": mechanics_pass,
        "reasons": hard_reasons,
        "policy": asdict(policy),
        "sample_count": sample_count,
        "duration_seconds": duration,
        "trend_sample_count": len(trend_samples),
        "rss": {
            "slope_mib_per_hour": rss_slope,
            "growth_mib_after_warmup": rss_growth,
            "peak_mib": peak_rss,
            "peak_cgroup_memory_mib": peak_memory_current,
        },
        "events": events,
    }


def render_markdown(result: dict[str, Any]) -> str:
    rss = result["rss"]
    lines = [
        "# Server-streaming soak report",
        "",
        f"Evidence class: `{result['evidence_class']}`  ",
        f"Verdict: **`{result['verdict']}`**  ",
        f"Mechanics pass: `{str(result['mechanics_pass']).lower()}`  ",
        f"Duration: `{result['duration_seconds']:.1f}` s  ",
        f"Samples: `{result['sample_count']}` (`{result['trend_sample_count']}` after warmup)",
        "",
        "## Memory trend",
        "",
        f"- RSS slope: `{rss['slope_mib_per_hour']:+.3f} MiB/hour`",
        f"- RSS growth after warmup: `{rss['growth_mib_after_warmup']:+.3f} MiB`",
        f"- peak RSS: `{rss['peak_mib']:.3f} MiB`",
        f"- peak cgroup memory.current: `{rss['peak_cgroup_memory_mib']:.3f} MiB`",
        "",
        "## Lifecycle gates",
        "",
    ]
    events = result.get("events", {})
    for name in ("host", "steady", "churn", "cancel", "backend_restart", "transport_reset", "final_probe", "nginx"):
        lines.append(f"- `{name}`: `{json.dumps(events.get(name, {}), sort_keys=True)}`")
    lines.extend(["", "## Reasons", ""])
    lines.extend((f"- `{reason}`" for reason in result["reasons"])) if result["reasons"] else lines.append("- all configured soak gates passed")
    lines.extend(["", "`harness_only` validates orchestration only. Production soak evidence requires strict host preflight, configured duration/sample count and all lifecycle/memory gates to pass.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", required=True, type=Path)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown", required=True, type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--container", default="nginx")
    args = parser.parse_args()
    samples = parse_stats(args.stats, container=args.container)
    events = json.loads(args.events.read_text(encoding="utf-8"))
    policy = SoakPolicy.from_dict(json.loads(args.policy.read_text(encoding="utf-8")))
    result = evaluate_soak({"strict": args.strict, "samples": samples, "events": events}, policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(result), encoding="utf-8")
    if args.strict and result["verdict"] != "soak_pass":
        return 1
    if not args.strict and not result["mechanics_pass"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
