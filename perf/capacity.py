#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SLO:
    max_error_rate: float | None = None
    max_p99_backend_to_client_ms: float | None = None
    max_p99_ttfd_ms: float | None = None
    max_avg_gateway_cores: float | None = None
    max_peak_rss_mib: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SLO":
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"unknown SLO fields: {', '.join(unknown)}")
        values: dict[str, float | None] = {}
        for key in allowed:
            value = data.get(key)
            values[key] = None if value is None else float(value)
        slo = cls(**values)
        slo.validate()
        return slo

    def validate(self) -> None:
        active = 0
        for name, value in asdict(self).items():
            if value is None:
                continue
            active += 1
            if value < 0:
                raise ValueError(f"{name} must be >= 0")
        if active == 0:
            raise ValueError("at least one SLO limit must be configured")
        if self.max_error_rate is not None and self.max_error_rate > 1:
            raise ValueError("max_error_rate must be between 0 and 1")


def classify_metrics(metrics: dict[str, Any], slo: SLO) -> dict[str, Any]:
    checks = [
        ("error_rate", slo.max_error_rate),
        ("p99_backend_to_client_ms", slo.max_p99_backend_to_client_ms),
        ("p99_ttfd_ms", slo.max_p99_ttfd_ms),
        ("avg_gateway_cores", slo.max_avg_gateway_cores),
        ("peak_rss_mib", slo.max_peak_rss_mib),
    ]
    reasons: list[str] = []
    observed: dict[str, float] = {}
    limits: dict[str, float] = {}
    for name, limit in checks:
        if limit is None:
            continue
        if name not in metrics:
            reasons.append(f"missing:{name}")
            continue
        value = float(metrics[name])
        observed[name] = value
        limits[name] = float(limit)
        if value > limit:
            reasons.append(name)
    return {
        "pass": not reasons,
        "reasons": reasons,
        "observed": observed,
        "limits": limits,
    }


def _matches(row: dict[str, Any], *, frontend: str, transport: str, payload_bytes: int,
             messages_per_stream: int, backend_delay_ms: int, consumer_delay_ms: int) -> bool:
    return (
        row.get("frontend") == frontend
        and row.get("transport") == transport
        and int(row.get("payload_bytes", -1)) == payload_bytes
        and int(row.get("messages_per_stream", -1)) == messages_per_stream
        and int(row.get("backend_delay_ms", -1)) == backend_delay_ms
        and int(row.get("consumer_delay_ms", -1)) == consumer_delay_ms
    )


def _architecture_capacity(points: list[dict[str, Any]]) -> dict[str, Any]:
    max_sustainable = 0
    first_failed: int | None = None
    still_contiguous = True
    for point in points:
        if still_contiguous and point["pass"]:
            max_sustainable = int(point["streams"])
            continue
        if still_contiguous:
            first_failed = int(point["streams"])
            still_contiguous = False
    return {
        "max_sustainable_streams": max_sustainable,
        "first_failed_streams": first_failed,
        "points": points,
    }


def evaluate_capacity(
    report: dict[str, Any],
    slo: SLO,
    *,
    frontend: str,
    transport: str,
    payload_bytes: int,
    messages_per_stream: int,
    backend_delay_ms: int,
    consumer_delay_ms: int,
    gateway_cpuset: str | None = None,
) -> dict[str, Any]:
    slo.validate()
    selected = [
        row for row in report.get("rows", [])
        if _matches(
            row,
            frontend=frontend,
            transport=transport,
            payload_bytes=payload_bytes,
            messages_per_stream=messages_per_stream,
            backend_delay_ms=backend_delay_ms,
            consumer_delay_ms=consumer_delay_ms,
        )
    ]
    selected.sort(key=lambda row: int(row["streams"]))
    if not selected:
        raise ValueError("no report rows match the requested capacity scenario")

    architectures: dict[str, Any] = {}
    for arch in ("legacy", "native"):
        points: list[dict[str, Any]] = []
        for row in selected:
            metrics = row.get(arch)
            if not isinstance(metrics, dict):
                raise ValueError(f"missing {arch} metrics at streams={row.get('streams')}")
            classified = classify_metrics(metrics, slo)
            points.append(
                {
                    "streams": int(row["streams"]),
                    "pass": classified["pass"],
                    "reasons": classified["reasons"],
                    "metrics": metrics,
                }
            )
        architectures[arch] = _architecture_capacity(points)

    legacy_capacity = architectures["legacy"]["max_sustainable_streams"]
    native_capacity = architectures["native"]["max_sustainable_streams"]
    capacity_delta = None
    if legacy_capacity > 0:
        capacity_delta = (native_capacity - legacy_capacity) / legacy_capacity * 100.0

    return {
        "version": 1,
        "scenario": {
            "frontend": frontend,
            "transport": transport,
            "payload_bytes": payload_bytes,
            "messages_per_stream": messages_per_stream,
            "backend_delay_ms": backend_delay_ms,
            "consumer_delay_ms": consumer_delay_ms,
            "gateway_cpuset": gateway_cpuset or "unconstrained",
        },
        "slo": asdict(slo),
        "architectures": architectures,
        "capacity_delta_percent": capacity_delta,
    }


def both_failed_at(result: dict[str, Any], streams: int) -> bool:
    for arch in ("legacy", "native"):
        points = result["architectures"][arch]["points"]
        point = next((item for item in points if int(item["streams"]) == streams), None)
        if point is None or point["pass"]:
            return False
    return True


def render_markdown(result: dict[str, Any]) -> str:
    scenario = result["scenario"]
    slo = result["slo"]
    lines = [
        "# Capacity / SLO report",
        "",
        f"Frontend: `{scenario['frontend']}`  ",
        f"Transport: `{scenario['transport']}`  ",
        f"Payload: `{scenario['payload_bytes']}` bytes  ",
        f"Messages per stream: `{scenario['messages_per_stream']}`  ",
        f"Backend delay: `{scenario['backend_delay_ms']}` ms  ",
        f"Consumer delay: `{scenario['consumer_delay_ms']}` ms  ",
        f"Gateway CPU set: `{scenario['gateway_cpuset']}`",
        "",
        "## SLO",
        "",
    ]
    for key, value in slo.items():
        if value is not None:
            lines.append(f"- `{key}` <= `{value}`")

    lines.extend(
        [
            "",
            "## Sustainable capacity",
            "",
            "| architecture | max sustainable streams | first failed streams |",
            "|---|---:|---:|",
        ]
    )
    for arch in ("legacy", "native"):
        item = result["architectures"][arch]
        failed = item["first_failed_streams"]
        lines.append(
            f"| {arch} | {item['max_sustainable_streams']} | {failed if failed is not None else 'not reached'} |"
        )

    delta = result["capacity_delta_percent"]
    lines.extend(["", f"Native capacity delta vs legacy: `{delta:+.1f}%`" if delta is not None else "Native capacity delta vs legacy: `n/a`", ""])

    for arch in ("legacy", "native"):
        lines.extend(
            [
                f"## {arch} staircase",
                "",
                "| streams | pass | reasons | error rate | p99 backend→client ms | p99 TTFD ms | avg gateway cores | peak RSS MiB |",
                "|---:|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for point in result["architectures"][arch]["points"]:
            m = point["metrics"]
            lines.append(
                "| {streams} | {passed} | {reasons} | {error_rate:.4f} | {backend:.2f} | {ttfd:.2f} | {cores:.3f} | {rss:.2f} |".format(
                    streams=point["streams"],
                    passed="yes" if point["pass"] else "no",
                    reasons=", ".join(point["reasons"]) or "-",
                    error_rate=float(m.get("error_rate", 0.0)),
                    backend=float(m.get("p99_backend_to_client_ms", 0.0)),
                    ttfd=float(m.get("p99_ttfd_ms", 0.0)),
                    cores=float(m.get("avg_gateway_cores", 0.0)),
                    rss=float(m.get("peak_rss_mib", 0.0)),
                )
            )
        lines.append("")

    lines.extend(
        [
            "Capacity is the highest contiguous passing staircase point from the lowest tested load. A later pass after the first failed level does not increase sustainable capacity.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--slo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--frontend", required=True, choices=("http1", "tls-h2"))
    parser.add_argument("--transport", default="text", choices=("text", "binary"))
    parser.add_argument("--payload-bytes", type=int, default=4096)
    parser.add_argument("--messages", type=int, default=20)
    parser.add_argument("--delay-ms", type=int, default=20)
    parser.add_argument("--consumer-delay-ms", type=int, default=0)
    parser.add_argument("--gateway-cpuset")
    parser.add_argument("--probe-streams", type=int)
    parser.add_argument("--exit-both-failed", action="store_true")
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    slo = SLO.from_dict(json.loads(args.slo.read_text(encoding="utf-8")))
    result = evaluate_capacity(
        report,
        slo,
        frontend=args.frontend,
        transport=args.transport,
        payload_bytes=args.payload_bytes,
        messages_per_stream=args.messages,
        backend_delay_ms=args.delay_ms,
        consumer_delay_ms=args.consumer_delay_ms,
        gateway_cpuset=args.gateway_cpuset,
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(render_markdown(result), encoding="utf-8")

    if args.exit_both_failed:
        if args.probe_streams is None:
            raise SystemExit("--exit-both-failed requires --probe-streams")
        if both_failed_at(result, args.probe_streams):
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
