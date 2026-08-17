#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class RCInputError(ValueError):
    pass


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise RCInputError(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RCInputError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RCInputError(f"{label} must be a JSON object: {path}")
    return value


def parse_steps(value: str) -> list[int]:
    try:
        steps = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise RCInputError(f"capacity steps must be integers: {value!r}") from exc
    if not steps:
        raise RCInputError("capacity steps must not be empty")
    if any(step <= 0 for step in steps):
        raise RCInputError("capacity steps must be positive")
    if any(right <= left for left, right in zip(steps, steps[1:])):
        raise RCInputError("capacity steps must be strictly increasing")
    return steps


def extend_steps(steps: list[int], *, max_streams: int) -> list[int]:
    if max_streams <= 0:
        raise RCInputError("max_streams must be positive")
    if not steps:
        raise RCInputError("cannot extend an empty staircase")
    last = steps[-1]
    if last >= max_streams:
        raise RCInputError(f"capacity boundary not reached before configured ceiling {max_streams}")
    next_step = min(last * 2, max_streams)
    if next_step <= last:
        raise RCInputError(f"cannot extend capacity staircase beyond {last}")
    return [*steps, next_step]


def _required_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise RCInputError(f"{label} must be a JSON boolean")
    return value


def _required_int(value: Any, label: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RCInputError(f"{label} must be an integer >= {minimum}")
    return value


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RCInputError(f"{label} must be a non-empty string")
    return value.strip()


def _arch_capacity(capacity: dict[str, Any], arch: str, repeat: str) -> dict[str, Any]:
    architectures = capacity.get("architectures")
    if not isinstance(architectures, dict):
        raise RCInputError(f"{repeat} capacity.architectures must be an object")
    result = architectures.get(arch)
    if not isinstance(result, dict):
        raise RCInputError(f"{repeat} missing {arch} capacity result")
    return result


def _expected_scenario(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "frontend": _required_string(manifest.get("frontend"), "manifest.frontend"),
        "transport": _required_string(manifest.get("transport"), "manifest.transport"),
        "payload_bytes": _required_int(manifest.get("payload_bytes"), "manifest.payload_bytes", minimum=0),
        "messages_per_stream": _required_int(manifest.get("messages"), "manifest.messages", minimum=1),
        "backend_delay_ms": _required_int(manifest.get("backend_delay_ms"), "manifest.backend_delay_ms", minimum=0),
        "consumer_delay_ms": _required_int(manifest.get("consumer_delay_ms"), "manifest.consumer_delay_ms", minimum=0),
        "gateway_cpuset": _required_string(manifest.get("gateway_cpuset"), "manifest.gateway_cpuset"),
    }


def _validate_capacity_scenario(capacity: dict[str, Any], expected: dict[str, Any], repeat: str) -> None:
    scenario = capacity.get("scenario")
    if not isinstance(scenario, dict):
        raise RCInputError(f"{repeat} capacity.scenario must be an object")
    for key, expected_value in expected.items():
        if scenario.get(key) != expected_value:
            raise RCInputError(
                f"{repeat} scenario mismatch for {key}: expected {expected_value!r}, got {scenario.get(key)!r}"
            )


def evaluate_scenario(root: Path, *, min_repeats: int = 5) -> dict[str, Any]:
    if min_repeats < 2:
        raise RCInputError("min_repeats must be >= 2")

    manifest = load_json(root / "manifest.json", "controlled manifest")
    decision = load_json(root / "decision.json", "controlled decision")

    if _required_bool(manifest.get("strict_preflight"), "manifest.strict_preflight") is not True:
        raise RCInputError("release-quality scenario requires strict_preflight=true")

    source_commit = _required_string(manifest.get("git_commit"), "manifest.git_commit")
    nginx_version = _required_string(manifest.get("nginx_version"), "manifest.nginx_version")
    compiler = _required_string(manifest.get("build_cc"), "manifest.build_cc")
    expected_scenario = _expected_scenario(manifest)
    if expected_scenario["frontend"] != "tls-h2":
        raise RCInputError("release-quality scenario requires frontend=tls-h2")
    if str(decision.get("evidence_class", "")) != "controlled":
        raise RCInputError("release-quality scenario requires evidence_class=controlled")

    decision_fingerprint = _required_string(decision.get("host_fingerprint"), "decision.host_fingerprint")

    repeat_dirs = sorted(path for path in root.glob("repeat-*") if path.is_dir())
    if len(repeat_dirs) < min_repeats:
        raise RCInputError(f"need at least {min_repeats} strict repeats, found {len(repeat_dirs)}")

    manifest_repeats = _required_int(manifest.get("repeats"), "manifest.repeats", minimum=1)
    decision_repeats = _required_int(decision.get("repeats"), "decision.repeats", minimum=1)
    if manifest_repeats != len(repeat_dirs):
        raise RCInputError(
            f"manifest repeat count {manifest_repeats} does not match raw repeat directories {len(repeat_dirs)}"
        )
    if decision_repeats != len(repeat_dirs):
        raise RCInputError(
            f"decision repeat count {decision_repeats} does not match raw repeat directories {len(repeat_dirs)}"
        )

    boundary_missing: dict[str, list[str]] = {"legacy": [], "native": []}
    fingerprints: set[str] = set()
    per_repeat: list[dict[str, Any]] = []

    for repeat_dir in repeat_dirs:
        host = load_json(repeat_dir / "host.json", f"{repeat_dir.name} host")
        capacity = load_json(repeat_dir / "capacity.json", f"{repeat_dir.name} capacity")

        if _required_bool(host.get("strict"), f"{repeat_dir.name}.host.strict") is not True:
            raise RCInputError(f"{repeat_dir.name} host is not strict")
        if _required_bool(host.get("valid"), f"{repeat_dir.name}.host.valid") is not True:
            raise RCInputError(f"{repeat_dir.name} host preflight is invalid")
        fingerprint = _required_string(host.get("fingerprint"), f"{repeat_dir.name}.host.fingerprint")
        fingerprints.add(fingerprint)
        _validate_capacity_scenario(capacity, expected_scenario, repeat_dir.name)

        repeat_result: dict[str, Any] = {"repeat": repeat_dir.name, "host_fingerprint": fingerprint}
        for arch in ("legacy", "native"):
            arch_result = _arch_capacity(capacity, arch, repeat_dir.name)
            max_sustainable = arch_result.get("max_sustainable_streams")
            first_failed = arch_result.get("first_failed_streams")
            if not isinstance(max_sustainable, int) or isinstance(max_sustainable, bool) or max_sustainable < 0:
                raise RCInputError(f"{repeat_dir.name} {arch}.max_sustainable_streams must be a non-negative integer")
            if first_failed is not None and (
                not isinstance(first_failed, int) or isinstance(first_failed, bool) or first_failed <= 0
            ):
                raise RCInputError(f"{repeat_dir.name} {arch}.first_failed_streams must be null or a positive integer")
            if first_failed is not None and first_failed <= max_sustainable:
                raise RCInputError(
                    f"{repeat_dir.name} {arch}.first_failed_streams must be greater than max_sustainable_streams"
                )
            if first_failed is None:
                boundary_missing[arch].append(repeat_dir.name)
            repeat_result[arch] = {
                "max_sustainable_streams": max_sustainable,
                "first_failed_streams": first_failed,
            }
        per_repeat.append(repeat_result)

    if fingerprints != {decision_fingerprint}:
        raise RCInputError(
            "repeat host fingerprints do not match the controlled decision fingerprint: "
            f"decision={decision_fingerprint}, repeats={sorted(fingerprints)}"
        )

    boundaries_complete = not boundary_missing["legacy"] and not boundary_missing["native"]
    reasons: list[str] = []
    if not boundaries_complete:
        reasons.append("capacity_boundary_not_reached")

    recommendation = _required_string(decision.get("recommendation"), "decision.recommendation")
    if recommendation != "native_preferred":
        reasons.append("decision_inconclusive" if recommendation == "inconclusive" else "decision_not_native_preferred")

    decision_reasons = decision.get("decision_reasons", [])
    if not isinstance(decision_reasons, list) or not all(isinstance(item, str) for item in decision_reasons):
        raise RCInputError("decision.decision_reasons must be an array of strings")
    if decision_reasons:
        reasons.append("decision_reasons_present")

    reference = decision.get("reference") if isinstance(decision.get("reference"), dict) else {}
    median_delta = reference.get("median_delta_percent") if isinstance(reference.get("median_delta_percent"), dict) else {}
    ready = not reasons

    return {
        "version": 1,
        "source_commit": source_commit,
        "nginx_version": nginx_version,
        "compiler": compiler,
        "frontend": expected_scenario["frontend"],
        "transport": expected_scenario["transport"],
        "payload_bytes": expected_scenario["payload_bytes"],
        "messages": expected_scenario["messages_per_stream"],
        "backend_delay_ms": expected_scenario["backend_delay_ms"],
        "consumer_delay_ms": expected_scenario["consumer_delay_ms"],
        "gateway_cpuset": expected_scenario["gateway_cpuset"],
        "capacity_steps": _required_string(manifest.get("capacity_steps"), "manifest.capacity_steps"),
        "repeat_count": len(repeat_dirs),
        "host_fingerprint": decision_fingerprint,
        "evidence_class": "controlled",
        "recommendation": recommendation,
        "decision_reasons": list(decision_reasons),
        "capacity": decision.get("capacity", {}),
        "capacity_delta_percent": decision.get("capacity_delta_percent"),
        "reference_streams": reference.get("streams"),
        "same_load_delta_percent": median_delta,
        "boundaries_complete": boundaries_complete,
        "boundary_missing": boundary_missing,
        "ready": ready,
        "reasons": reasons,
        "per_repeat": per_repeat,
    }


def render_scenario(result: dict[str, Any]) -> str:
    lines = [
        "# M15 controlled RC scenario",
        "",
        f"Source: `{result['source_commit']}`  ",
        f"Host fingerprint: `{result['host_fingerprint']}`  ",
        f"Evidence: `{result['evidence_class']}`  ",
        f"Recommendation: **`{result['recommendation']}`**  ",
        f"Boundaries complete: `{str(result['boundaries_complete']).lower()}`  ",
        f"Ready: **`{str(result['ready']).lower()}`**",
        "",
        "## Scenario",
        "",
        f"- frontend: `{result['frontend']}`",
        f"- transport: `{result['transport']}`",
        f"- payload bytes: `{result['payload_bytes']}`",
        f"- messages: `{result['messages']}`",
        f"- backend delay: `{result['backend_delay_ms']} ms`",
        f"- consumer delay: `{result['consumer_delay_ms']} ms`",
        f"- capacity steps: `{result['capacity_steps']}`",
        f"- repeats: `{result['repeat_count']}`",
        "",
        "## Capacity",
        "",
    ]
    for arch in ("legacy", "native"):
        cap = result.get("capacity", {}).get(arch, {}) if isinstance(result.get("capacity"), dict) else {}
        lines.append(
            f"- {arch}: min `{cap.get('min', 'n/a')}`, median `{cap.get('median', 'n/a')}`, "
            f"max `{cap.get('max', 'n/a')}`, CV `{cap.get('cv', 'n/a')}`"
        )
    lines.extend([
        f"- native capacity delta: `{result.get('capacity_delta_percent')}`",
        f"- conservative reference load: `{result.get('reference_streams')}` streams",
        "",
        "## Same-load native delta vs legacy",
        "",
    ])
    deltas = result.get("same_load_delta_percent", {})
    if isinstance(deltas, dict) and deltas:
        for name, value in sorted(deltas.items()):
            lines.append(f"- `{name}`: `{value}`")
    else:
        lines.append("- no comparable same-load delta")
    lines.extend(["", "## Boundary status", ""])
    for arch in ("legacy", "native"):
        missing = result["boundary_missing"][arch]
        lines.append(f"- {arch}: {'complete' if not missing else 'missing in ' + ', '.join(missing)}")
    lines.extend(["", "## Reasons", ""])
    lines.extend(f"- `{reason}`" for reason in result["reasons"]) if result["reasons"] else lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def aggregate_scenarios(entries: list[tuple[str, Path]]) -> dict[str, Any]:
    if not entries:
        raise RCInputError("at least one scenario summary is required")
    scenarios: dict[str, dict[str, Any]] = {}
    commits: set[str] = set()
    fingerprints: set[str] = set()
    nginx_versions: set[str] = set()
    compilers: set[str] = set()
    for name, path in entries:
        if not name or name in scenarios:
            raise RCInputError(f"duplicate/empty scenario name: {name!r}")
        result = load_json(path, f"scenario summary {name}")
        scenarios[name] = result
        commits.add(str(result.get("source_commit", "")))
        fingerprints.add(str(result.get("host_fingerprint", "")))
        nginx_versions.add(str(result.get("nginx_version", "")))
        compilers.add(str(result.get("compiler", "")))
    blockers: list[str] = []
    if "" in commits or len(commits) != 1:
        blockers.append("mixed_source_commit")
    if "" in fingerprints or len(fingerprints) != 1:
        blockers.append("mixed_host_fingerprint")
    if "" in nginx_versions or len(nginx_versions) != 1:
        blockers.append("mixed_nginx_version")
    if "" in compilers or len(compilers) != 1:
        blockers.append("mixed_compiler")
    for name, result in scenarios.items():
        if result.get("evidence_class") != "controlled":
            blockers.append(f"{name}:not_controlled")
        if result.get("boundaries_complete") is not True:
            blockers.append(f"{name}:capacity_boundary")
        if result.get("ready") is not True:
            blockers.append(f"{name}:not_ready")
    return {
        "version": 1,
        "source_commit": next(iter(commits)) if len(commits) == 1 else "",
        "host_fingerprint": next(iter(fingerprints)) if len(fingerprints) == 1 else "",
        "nginx_version": next(iter(nginx_versions)) if len(nginx_versions) == 1 else "",
        "compiler": next(iter(compilers)) if len(compilers) == 1 else "",
        "ready": not blockers,
        "blockers": blockers,
        "scenarios": scenarios,
    }


def render_aggregate(result: dict[str, Any]) -> str:
    lines = [
        "# M15 controlled RC benchmark summary",
        "",
        f"Source: `{result['source_commit']}`  ",
        f"Host fingerprint: `{result['host_fingerprint']}`  ",
        f"NGINX/compiler: `{result['nginx_version']}` / `{result['compiler']}`  ",
        f"Ready: **`{str(result['ready']).lower()}`**",
        "",
        "| scenario | boundaries | recommendation | legacy median | native median | capacity delta | CPU delta | RSS delta | p99 TTFD delta |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, scenario in result["scenarios"].items():
        capacity = scenario.get("capacity", {}) if isinstance(scenario.get("capacity"), dict) else {}
        legacy = capacity.get("legacy", {}) if isinstance(capacity.get("legacy"), dict) else {}
        native = capacity.get("native", {}) if isinstance(capacity.get("native"), dict) else {}
        deltas = scenario.get("same_load_delta_percent", {}) if isinstance(scenario.get("same_load_delta_percent"), dict) else {}
        lines.append(
            "| {name} | {bounds} | {rec} | {legacy} | {native} | {cap} | {cpu} | {rss} | {ttfd} |".format(
                name=name,
                bounds="yes" if scenario.get("boundaries_complete") is True else "no",
                rec=scenario.get("recommendation", ""),
                legacy=legacy.get("median", "n/a"),
                native=native.get("median", "n/a"),
                cap=scenario.get("capacity_delta_percent", "n/a"),
                cpu=deltas.get("avg_gateway_cores", "n/a"),
                rss=deltas.get("peak_rss_mib", "n/a"),
                ttfd=deltas.get("p99_ttfd_ms", "n/a"),
            )
        )
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- `{item}`" for item in result["blockers"]) if result["blockers"] else lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check")
    check.add_argument("--input", required=True, type=Path)
    check.add_argument("--min-repeats", type=int, default=5)
    check.add_argument("--output", required=True, type=Path)
    check.add_argument("--markdown", required=True, type=Path)

    extend = sub.add_parser("extend")
    extend.add_argument("--steps", required=True)
    extend.add_argument("--max-streams", required=True, type=int)

    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("--scenario", action="append", default=[], metavar="NAME=PATH")
    aggregate.add_argument("--output", required=True, type=Path)
    aggregate.add_argument("--markdown", required=True, type=Path)

    args = parser.parse_args()
    try:
        if args.command == "check":
            result = evaluate_scenario(args.input, min_repeats=args.min_repeats)
            _write(args.output, json.dumps(result, indent=2, sort_keys=True) + "\n")
            _write(args.markdown, render_scenario(result))
            return 0 if result["ready"] else 3
        if args.command == "extend":
            steps = extend_steps(parse_steps(args.steps), max_streams=args.max_streams)
            print(",".join(str(step) for step in steps))
            return 0
        entries: list[tuple[str, Path]] = []
        for raw in args.scenario:
            if "=" not in raw:
                raise RCInputError(f"scenario must use NAME=PATH: {raw!r}")
            name, path = raw.split("=", 1)
            entries.append((name.strip(), Path(path)))
        result = aggregate_scenarios(entries)
        _write(args.output, json.dumps(result, indent=2, sort_keys=True) + "\n")
        _write(args.markdown, render_aggregate(result))
        return 0 if result["ready"] else 1
    except (RCInputError, ValueError) as exc:
        print(f"rc benchmark input error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
