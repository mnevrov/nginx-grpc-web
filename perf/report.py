#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

MIB = 1024 * 1024
GIB = 1024 * MIB


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    if q <= 0:
        return values[0]
    if q >= 1:
        return values[-1]
    pos = q * (len(values) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return values[lo] + (values[hi] - values[lo]) * frac


def read_stats(path: Path) -> dict[str, float]:
    if not path.exists():
        raise RuntimeError(f"missing gateway stats file: {path}")

    cpu_by_container: dict[str, list[int]] = defaultdict(list)
    rss_by_timestamp: dict[str, int] = defaultdict(int)
    memory_by_timestamp: dict[str, int] = defaultdict(int)

    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            ts = row["timestamp"]
            container = row["container"]
            cpu_by_container[container].append(int(row["cpu_usage_usec"]))
            rss_by_timestamp[ts] += int(row["rss_bytes"])
            memory_by_timestamp[ts] += int(row["memory_current_bytes"])

    samples = len(memory_by_timestamp)
    if samples < 2:
        raise RuntimeError(
            f"gateway stats need at least two cgroup samples, got {samples}: {path}"
        )

    cpu_core_seconds = 0.0
    for container, values in cpu_by_container.items():
        if len(values) < 2:
            raise RuntimeError(
                f"gateway stats need two CPU samples for {container}: {path}"
            )
        delta_usec = values[-1] - values[0]
        if delta_usec < 0:
            raise RuntimeError(
                f"cgroup CPU counter moved backwards for {container}: {path}"
            )
        cpu_core_seconds += delta_usec / 1_000_000.0

    return {
        "cpu_core_seconds": cpu_core_seconds,
        "peak_rss_mib": max(rss_by_timestamp.values()) / MIB,
        "peak_cgroup_memory_mib": max(memory_by_timestamp.values()) / MIB,
        "samples": samples,
    }


def scenario_key(data: dict) -> tuple:
    cfg = data["config"]
    return (
        cfg.get("frontend", "http1"),
        cfg["transport"],
        int(cfg["payload_bytes"]),
        int(cfg["streams"]),
        int(cfg["messages_per_stream"]),
        int(cfg["backend_delay_ms"]),
        int(cfg["consumer_delay_ms"]),
    )


def aggregate(runs: list[dict]) -> dict:
    ttfd: list[float] = []
    added: list[float] = []
    inter: list[float] = []
    durations: list[float] = []
    payload_bytes = 0
    wire_bytes = 0
    data_frames = 0
    errors = 0
    wall_seconds = 0.0
    cpu_core_seconds = 0.0
    peak_rss_mib = 0.0
    peak_cgroup_memory_mib = 0.0
    stats_samples = 0
    http_protocols: set[str] = set()
    tls_alpn: set[str] = set()
    tls_versions: set[str] = set()

    for item in runs:
        data = item["data"]
        stats = item["stats"]
        summary = data["summary"]
        wall = float(summary["wall_seconds"])
        wall_seconds += wall
        payload_bytes += int(summary["payload_bytes"])
        wire_bytes += int(summary["wire_bytes"])
        data_frames += int(summary["data_frames"])
        errors += int(summary["errors"])
        cpu_core_seconds += stats["cpu_core_seconds"]
        peak_rss_mib = max(peak_rss_mib, stats["peak_rss_mib"])
        peak_cgroup_memory_mib = max(
            peak_cgroup_memory_mib, stats["peak_cgroup_memory_mib"]
        )
        stats_samples += int(stats["samples"])

        for stream in data.get("streams", []):
            if stream.get("error"):
                continue
            if stream.get("http_protocol"):
                http_protocols.add(stream["http_protocol"])
            if stream.get("tls_alpn"):
                tls_alpn.add(stream["tls_alpn"])
            if stream.get("tls_version"):
                tls_versions.add(stream["tls_version"])
            ttfd.append(float(stream.get("ttfd_ms", 0.0)))
            durations.append(float(stream.get("duration_ms", 0.0)))
            added.extend(float(v) for v in stream.get("backend_to_client_ms", []))
            inter.extend(float(v) for v in stream.get("inter_arrival_ms", []))

    gib = payload_bytes / GIB
    return {
        "runs": len(runs),
        "errors": errors,
        "data_frames": data_frames,
        "payload_bytes": payload_bytes,
        "wire_bytes": wire_bytes,
        "wall_seconds": wall_seconds,
        "messages_per_second": data_frames / wall_seconds if wall_seconds else 0.0,
        "mib_per_second": payload_bytes / MIB / wall_seconds if wall_seconds else 0.0,
        "wire_amplification": wire_bytes / payload_bytes if payload_bytes else 0.0,
        "p99_ttfd_ms": percentile(ttfd, 0.99),
        "p99_backend_to_client_ms": percentile(added, 0.99),
        "p99_inter_arrival_ms": percentile(inter, 0.99),
        "p99_stream_duration_ms": percentile(durations, 0.99),
        "cpu_core_seconds": cpu_core_seconds,
        "cpu_core_seconds_per_gib": cpu_core_seconds / gib if gib else 0.0,
        "peak_rss_mib": peak_rss_mib,
        "peak_cgroup_memory_mib": peak_cgroup_memory_mib,
        "stats_samples": stats_samples,
        "http_protocols": sorted(http_protocols),
        "tls_alpn": sorted(tls_alpn),
        "tls_versions": sorted(tls_versions),
    }


def delta_percent(native: float, legacy: float) -> float | None:
    if legacy == 0:
        return None
    return (native - legacy) / legacy * 100.0


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def fmt_delta(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    grouped: dict[tuple, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for path in sorted(args.input.glob("*.json")):
        if path.name == "report.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if "config" not in data or "summary" not in data:
            continue
        arch = data["config"].get("name")
        if arch not in {"native", "legacy"}:
            continue
        stats_path = path.with_suffix(".stats.tsv")
        grouped[scenario_key(data)][arch].append(
            {"path": str(path), "data": data, "stats": read_stats(stats_path)}
        )

    rows = []
    for key in sorted(grouped):
        frontend, transport, payload, streams, messages, delay, consumer_delay = key
        if "native" not in grouped[key] or "legacy" not in grouped[key]:
            continue
        legacy = aggregate(grouped[key]["legacy"])
        native = aggregate(grouped[key]["native"])
        rows.append(
            {
                "frontend": frontend,
                "transport": transport,
                "payload_bytes": payload,
                "streams": streams,
                "messages_per_stream": messages,
                "backend_delay_ms": delay,
                "consumer_delay_ms": consumer_delay,
                "legacy": legacy,
                "native": native,
                "delta": {
                    "p99_ttfd_ms": delta_percent(native["p99_ttfd_ms"], legacy["p99_ttfd_ms"]),
                    "p99_backend_to_client_ms": delta_percent(
                        native["p99_backend_to_client_ms"], legacy["p99_backend_to_client_ms"]
                    ),
                    "mib_per_second": delta_percent(native["mib_per_second"], legacy["mib_per_second"]),
                    "cpu_core_seconds_per_gib": delta_percent(
                        native["cpu_core_seconds_per_gib"], legacy["cpu_core_seconds_per_gib"]
                    ),
                    "peak_rss_mib": delta_percent(native["peak_rss_mib"], legacy["peak_rss_mib"]),
                    "peak_cgroup_memory_mib": delta_percent(
                        native["peak_cgroup_memory_mib"], legacy["peak_cgroup_memory_mib"]
                    ),
                },
            }
        )

    output = {
        "version": 2,
        "source": str(args.input),
        "comparison": "legacy NGINX -> Envoy vs native NGINX(module)",
        "rows": rows,
    }
    if args.json_output:
        args.json_output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# gRPC-Web server streaming performance report",
        "",
        "`legacy` = NGINX -> Envoy grpc_web -> native gRPC backend.  ",
        "`native` = NGINX + ngx_http_grpc_web_module -> native gRPC backend.",
        "",
        "Negative delta is better for latency/CPU/RSS; positive delta is better for throughput.",
        "",
        "| frontend | transport | payload | streams | p99 TTFD legacy/native | Δ | p99 backend→client legacy/native | Δ | MiB/s legacy/native | Δ | CPU core-s/GiB legacy/native | Δ | peak RSS MiB legacy/native | errors L/N |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for row in rows:
        legacy = row["legacy"]
        native = row["native"]
        delta = row["delta"]
        payload = row["payload_bytes"]
        payload_label = f"{payload / MIB:.0f} MiB" if payload >= MIB else f"{payload / 1024:.0f} KiB"
        lines.append(
            "| {frontend} | {transport} | {payload} | {streams} | {lttfd}/{nttfd} ms | {dttfd} | "
            "{ladd}/{nadd} ms | {dadd} | {lmb}/{nmb} | {dmb} | {lcpu}/{ncpu} | {dcpu} | "
            "{lrss}/{nrss} | {le}/{ne} |".format(
                frontend=row["frontend"],
                transport=row["transport"],
                payload=payload_label,
                streams=row["streams"],
                lttfd=fmt(legacy["p99_ttfd_ms"]),
                nttfd=fmt(native["p99_ttfd_ms"]),
                dttfd=fmt_delta(delta["p99_ttfd_ms"]),
                ladd=fmt(legacy["p99_backend_to_client_ms"]),
                nadd=fmt(native["p99_backend_to_client_ms"]),
                dadd=fmt_delta(delta["p99_backend_to_client_ms"]),
                lmb=fmt(legacy["mib_per_second"]),
                nmb=fmt(native["mib_per_second"]),
                dmb=fmt_delta(delta["mib_per_second"]),
                lcpu=fmt(legacy["cpu_core_seconds_per_gib"]),
                ncpu=fmt(native["cpu_core_seconds_per_gib"]),
                dcpu=fmt_delta(delta["cpu_core_seconds_per_gib"]),
                lrss=fmt(legacy["peak_rss_mib"]),
                nrss=fmt(native["peak_rss_mib"]),
                le=legacy["errors"],
                ne=native["errors"],
            )
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The `backend→client` metric uses a backend-relative timestamp taken immediately before `grpc.aio` yields each response. It includes protobuf serialization/native gRPC transport plus gateway/downstream delivery; because the backend is identical for both paths, the A/B delta is the useful signal.",
            "",
            "Gateway CPU is measured from cgroup v2 cumulative `usage_usec` before/through/after each measured run. Legacy CPU is the sum of front NGINX + Envoy; native CPU is the NGINX(module) cgroup.",
            "",
            "Peak RSS is the maximum sampled sum of process `VmRSS` for all PIDs in the relevant container cgroups. `report.json` additionally records `peak_cgroup_memory_mib` from `memory.current`, which includes cache and other cgroup-charged memory and is intentionally not labelled RSS.",
            "",
            "For `frontend=tls-h2`, the load generator requires HTTPS, validates the benchmark CA, requires response HTTP/2 and ALPN `h2`, and records negotiated HTTP/TLS metadata per stream. A silent HTTP/1.1 fallback is therefore a failed run, not a benchmark sample.",
            "",
            "Use a dedicated host and longer A/B/B/A measurement windows for release-quality CPU/GiB and latency conclusions. The GitHub Actions smoke result validates the harness only.",
            "",
        ]
    )
    args.output.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
