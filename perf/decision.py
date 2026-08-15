#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DecisionPolicy:
    min_repeats: int = 3
    max_capacity_cv: float = 0.20
    min_capacity_gain_percent: float = 10.0
    min_cpu_saving_percent: float = 10.0
    min_rss_saving_percent: float = 10.0
    max_p99_ttfd_regression_percent: float = 5.0
    max_p99_backend_to_client_regression_percent: float = 5.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionPolicy":
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"unknown decision policy fields: {', '.join(unknown)}")
        policy = cls(**data)
        policy.validate()
        return policy

    def validate(self) -> None:
        if self.min_repeats < 2:
            raise ValueError("min_repeats must be >= 2")
        for name, value in asdict(self).items():
            if name == "min_repeats":
                continue
            if float(value) < 0:
                raise ValueError(f"{name} must be >= 0")


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def _cv(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return math.inf if any(values) else 0.0
    return float(statistics.pstdev(values) / mean)


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "min": float(min(values)),
        "median": _median(values),
        "max": float(max(values)),
        "cv": _cv(values),
    }


def _scenario_key(result: dict[str, Any]) -> tuple[Any, ...]:
    scenario = result.get("scenario", {})
    return (
        scenario.get("frontend"),
        scenario.get("transport"),
        int(scenario.get("payload_bytes", -1)),
        int(scenario.get("messages_per_stream", -1)),
        int(scenario.get("backend_delay_ms", -1)),
        int(scenario.get("consumer_delay_ms", -1)),
        scenario.get("gateway_cpuset"),
    )


def _delta_percent(native: float, legacy: float) -> float | None:
    if legacy == 0:
        return None
    return (native - legacy) / legacy * 100.0


def _point_metrics(result: dict[str, Any], arch: str, streams: int) -> dict[str, Any] | None:
    points = result.get("architectures", {}).get(arch, {}).get("points", [])
    for point in points:
        if int(point.get("streams", -1)) == streams:
            return point.get("metrics") if isinstance(point.get("metrics"), dict) else None
    return None


def _reference_delta(result: dict[str, Any], streams: int) -> dict[str, float]:
    # Unit fixtures and imported historical results may already contain a normalized reference block.
    reference = result.get("reference")
    if isinstance(reference, dict) and int(reference.get("streams", -1)) == streams:
        delta = reference.get("delta_percent", {})
        if isinstance(delta, dict):
            return {key: float(value) for key, value in delta.items() if value is not None}

    legacy = _point_metrics(result, "legacy", streams)
    native = _point_metrics(result, "native", streams)
    if legacy is None or native is None:
        raise ValueError(f"capacity result has no comparable metrics at reference streams={streams}")

    metrics = (
        "p99_ttfd_ms",
        "p99_backend_to_client_ms",
        "avg_gateway_cores",
        "peak_rss_mib",
        "error_rate",
    )
    output: dict[str, float] = {}
    for name in metrics:
        lval = float(legacy.get(name, 0.0))
        nval = float(native.get(name, 0.0))
        if name == "error_rate":
            # Error rate is an absolute percentage-point delta to avoid division by zero at healthy baselines.
            output[name] = (nval - lval) * 100.0
        else:
            delta = _delta_percent(nval, lval)
            output[name] = 0.0 if delta is None else delta
    return output


def aggregate_repeats(repeats: list[dict[str, Any]], policy: DecisionPolicy) -> dict[str, Any]:
    policy.validate()
    if len(repeats) < policy.min_repeats:
        raise ValueError(f"need at least {policy.min_repeats} repeats, got {len(repeats)}")

    fingerprints = {str(item.get("host_fingerprint", "")) for item in repeats}
    if len(fingerprints) != 1 or "" in fingerprints:
        raise ValueError("all repeats must have the same non-empty host fingerprint")
    fingerprint = next(iter(fingerprints))

    scenarios = {_scenario_key(item) for item in repeats}
    if len(scenarios) != 1:
        raise ValueError("all repeats must use the same benchmark scenario")

    legacy_capacity = [float(item["architectures"]["legacy"]["max_sustainable_streams"]) for item in repeats]
    native_capacity = [float(item["architectures"]["native"]["max_sustainable_streams"]) for item in repeats]
    legacy_summary = _summary(legacy_capacity)
    native_summary = _summary(native_capacity)

    capacity_delta = _delta_percent(native_summary["median"], legacy_summary["median"])
    common_reference = int(min(min(legacy_capacity), min(native_capacity)))
    if common_reference <= 0:
        raise ValueError("no positive common sustainable reference load across repeats")

    per_repeat_delta = [_reference_delta(item, common_reference) for item in repeats]
    delta_names = {
        key
        for item in per_repeat_delta
        for key in item
    }
    median_deltas = {
        name: _median([item[name] for item in per_repeat_delta if name in item])
        for name in sorted(delta_names)
    }

    evidence_class = "controlled"
    host_records = [item.get("host") for item in repeats if isinstance(item.get("host"), dict)]
    if host_records:
        if not all(bool(host.get("strict")) and bool(host.get("valid")) for host in host_records):
            evidence_class = "harness_only"

    reasons: list[str] = []
    if legacy_summary["cv"] > policy.max_capacity_cv or native_summary["cv"] > policy.max_capacity_cv:
        reasons.append("capacity_variance")

    ttfd_delta = float(median_deltas.get("p99_ttfd_ms", 0.0))
    delivery_delta = float(median_deltas.get("p99_backend_to_client_ms", 0.0))
    if (
        ttfd_delta > policy.max_p99_ttfd_regression_percent
        or delivery_delta > policy.max_p99_backend_to_client_regression_percent
    ):
        reasons.append("latency_guardrail")

    benefit = False
    if capacity_delta is not None and capacity_delta >= policy.min_capacity_gain_percent:
        benefit = True
    if float(median_deltas.get("avg_gateway_cores", 0.0)) <= -policy.min_cpu_saving_percent:
        benefit = True
    if float(median_deltas.get("peak_rss_mib", 0.0)) <= -policy.min_rss_saving_percent:
        benefit = True
    if not benefit:
        reasons.append("no_material_benefit")

    if evidence_class != "controlled":
        reasons.append("harness_only")

    recommendation = "native_preferred" if not reasons else "inconclusive"
    scenario = repeats[0].get("scenario", {})
    return {
        "version": 1,
        "host_fingerprint": fingerprint,
        "evidence_class": evidence_class,
        "repeats": len(repeats),
        "scenario": scenario,
        "policy": asdict(policy),
        "capacity": {
            "legacy": legacy_summary,
            "native": native_summary,
        },
        "capacity_delta_percent": capacity_delta,
        "reference": {
            "streams": common_reference,
            "median_delta_percent": median_deltas,
            "repeat_delta_percent": per_repeat_delta,
        },
        "recommendation": recommendation,
        "decision_reasons": reasons,
    }


def render_markdown(result: dict[str, Any]) -> str:
    cap = result["capacity"]
    reference = result["reference"]
    delta = result.get("capacity_delta_percent")
    delta_text = "n/a" if delta is None else f"{delta:+.1f}%"
    md = reference.get("median_delta_percent", {})
    lines = [
        "# Controlled-host architecture decision",
        "",
        f"Host fingerprint: `{result['host_fingerprint']}`  ",
        f"Evidence class: `{result['evidence_class']}`  ",
        f"Repeats: `{result['repeats']}`  ",
        f"Recommendation: **`{result['recommendation']}`**",
        "",
        "## Sustainable capacity",
        "",
        "| architecture | min | median | max | CV |",
        "|---|---:|---:|---:|---:|",
        f"| legacy | {cap['legacy']['min']:.0f} | {cap['legacy']['median']:.0f} | {cap['legacy']['max']:.0f} | {cap['legacy']['cv']:.3f} |",
        f"| native | {cap['native']['min']:.0f} | {cap['native']['median']:.0f} | {cap['native']['max']:.0f} | {cap['native']['cv']:.3f} |",
        "",
        f"Native median capacity delta: **{delta_text}**",
        "",
        f"Reference load for same-load resource/latency comparison: `{reference['streams']}` streams.",
        "",
        "## Median native delta vs legacy at reference load",
        "",
        "| metric | delta | interpretation |",
        "|---|---:|---|",
    ]
    for name in ("p99_ttfd_ms", "p99_backend_to_client_ms", "avg_gateway_cores", "peak_rss_mib", "error_rate"):
        if name not in md:
            continue
        interpretation = "negative is better" if name != "error_rate" else "percentage-point delta; <= 0 is better"
        lines.append(f"| `{name}` | {float(md[name]):+.1f}% | {interpretation} |")

    lines.extend(["", "## Decision reasons", ""])
    if result["decision_reasons"]:
        lines.extend(f"- `{reason}`" for reason in result["decision_reasons"])
    else:
        lines.append("- all configured stability, latency and benefit guardrails passed")

    lines.extend(
        [
            "",
            "A `native_preferred` result is emitted only for controlled evidence. Shared CI or an unpinned/non-strict preflight is always `harness_only` and therefore `inconclusive`, regardless of the measured deltas.",
            "",
        ]
    )
    return "\n".join(lines)


def load_repeat_set(root: Path) -> list[dict[str, Any]]:
    repeats: list[dict[str, Any]] = []
    for repeat_dir in sorted(path for path in root.glob("repeat-*") if path.is_dir()):
        capacity_path = repeat_dir / "capacity.json"
        host_path = repeat_dir / "host.json"
        if not capacity_path.exists() or not host_path.exists():
            continue
        capacity = json.loads(capacity_path.read_text(encoding="utf-8"))
        host = json.loads(host_path.read_text(encoding="utf-8"))
        capacity["host_fingerprint"] = host.get("fingerprint", "")
        capacity["host"] = host
        repeats.append(capacity)
    return repeats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown", required=True, type=Path)
    args = parser.parse_args()

    policy = DecisionPolicy.from_dict(json.loads(args.policy.read_text(encoding="utf-8")))
    repeats = load_repeat_set(args.input)
    result = aggregate_repeats(repeats, policy)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
