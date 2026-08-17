#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "release"))
sys.path.insert(0, str(ROOT / "perf"))
from collect import EvidenceInputError  # noqa: E402
from revalidate import revalidate_controlled  # noqa: E402
from rc import RCInputError, aggregate_scenarios, evaluate_scenario, render_aggregate, render_scenario  # noqa: E402


class RCRevalidationError(ValueError):
    pass


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise RCRevalidationError(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RCRevalidationError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RCRevalidationError(f"{label} must be a JSON object: {path}")
    return value


def required_scenarios(manifest: dict[str, Any]) -> list[str]:
    result = ["typical", "large4m", "slow"]
    large8 = manifest.get("large8m")
    if not isinstance(large8, dict):
        raise RCRevalidationError("benchmark manifest large8m policy must be an object")
    requested = large8.get("requested")
    if type(requested) is not bool:
        raise RCRevalidationError("benchmark manifest large8m.requested must be a JSON boolean")
    if requested:
        result.append("large8m")
    else:
        reason = large8.get("skip_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise RCRevalidationError("8 MiB must be selected or have a non-empty skip reason")
    return result


def selected_attempts(benchmark_dir: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    selected = load_json(benchmark_dir / "selected-attempts.json", "selected attempts")
    result: dict[str, Path] = {}
    base = benchmark_dir.resolve()
    for name in required_scenarios(manifest):
        raw = selected.get(name)
        if not isinstance(raw, str) or not raw.strip():
            raise RCRevalidationError(f"missing selected attempt for {name}")
        path = Path(raw)
        if not path.is_absolute():
            path = (base / path).resolve()
        else:
            path = path.resolve()
        try:
            path.relative_to(base)
        except ValueError as exc:
            raise RCRevalidationError(f"selected attempt for {name} is outside benchmark directory: {path}") from exc
        if not path.is_dir():
            raise RCRevalidationError(f"selected attempt for {name} does not exist: {path}")
        result[name] = path
    return result


def semantic_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left == right


def revalidate_benchmark(*, repo_root: Path, benchmark_dir: Path, output_dir: Path) -> dict[str, Any]:
    benchmark_dir = benchmark_dir.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise RCRevalidationError(f"revalidation output already exists: {output_dir}")

    manifest = load_json(benchmark_dir / "manifest.json", "benchmark manifest")
    original = load_json(benchmark_dir / "rc-benchmark.json", "RC benchmark summary")
    repeat_count = manifest.get("repeats")
    if isinstance(repeat_count, bool) or not isinstance(repeat_count, int) or repeat_count < 5:
        raise RCRevalidationError("benchmark manifest repeats must be an integer >= 5")

    selected = selected_attempts(benchmark_dir, manifest)
    output_dir.mkdir(parents=True)
    scenario_entries: list[tuple[str, Path]] = []
    scenario_results: dict[str, dict[str, Any]] = {}

    try:
        for name, source_dir in selected.items():
            copied = output_dir / "controlled" / name
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_dir, copied)
            revalidate_controlled(repo_root, copied)
            summary = evaluate_scenario(copied, min_repeats=repeat_count)
            if summary.get("ready") is not True:
                raise RCRevalidationError(f"revalidated scenario {name} is not release-ready")
            summary_path = output_dir / "scenarios" / f"{name}.json"
            markdown_path = output_dir / "scenarios" / f"{name}.md"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            markdown_path.write_text(render_scenario(summary), encoding="utf-8")
            scenario_entries.append((name, summary_path))
            scenario_results[name] = summary

        aggregate = aggregate_scenarios(scenario_entries)
        if aggregate.get("ready") is not True:
            raise RCRevalidationError(f"revalidated aggregate is not ready: {aggregate.get('blockers')}")
        aggregate_path = output_dir / "rc-benchmark.revalidated.json"
        aggregate_md = output_dir / "rc-benchmark.revalidated.md"
        aggregate_path.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        aggregate_md.write_text(render_aggregate(aggregate), encoding="utf-8")

        if not semantic_equal(original, aggregate):
            raise RCRevalidationError("saved rc-benchmark.json does not match aggregate recomputed from selected raw evidence")

        result = {
            "version": 1,
            "valid": True,
            "source_commit": aggregate.get("source_commit", ""),
            "host_fingerprint": aggregate.get("host_fingerprint", ""),
            "scenario_names": list(selected),
            "scenario_count": len(selected),
            "original_summary_matches": True,
        }
    except (EvidenceInputError, RCInputError, RCRevalidationError, OSError, ValueError) as exc:
        result = {
            "version": 1,
            "valid": False,
            "reason": "rc_raw_revalidation",
            "error": str(exc),
        }
        (output_dir / "revalidation.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return result

    (output_dir / "revalidation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--benchmark-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    try:
        result = revalidate_benchmark(
            repo_root=args.repo_root.resolve(),
            benchmark_dir=args.benchmark_dir,
            output_dir=args.output_dir,
        )
    except (RCRevalidationError, OSError, ValueError) as exc:
        print(f"RC benchmark revalidation error: {exc}")
        return 2

    if result.get("valid") is not True:
        print(f"RC benchmark raw revalidation failed: {result.get('error', 'unknown error')}")
        return 1
    print(f"RC benchmark raw revalidation passed: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
