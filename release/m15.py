#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class M15EvidenceError(ValueError):
    pass


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise M15EvidenceError(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M15EvidenceError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise M15EvidenceError(f"{label} must be a JSON object: {path}")
    return value


def required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise M15EvidenceError(f"{label} must be a non-empty string")
    return value.strip()


def non_empty_file(path: Path, label: str) -> str:
    if not path.is_file():
        raise M15EvidenceError(f"missing {label}: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise M15EvidenceError(f"{label} must not be empty: {path}")
    return text


def evaluate(
    *,
    benchmark_manifest: dict[str, Any],
    benchmark: dict[str, Any],
    soak: dict[str, Any],
    staging: dict[str, Any],
    release_evidence: dict[str, Any],
    eight_hour_waiver: str | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    advisory: list[str] = []

    source = required_string(benchmark.get("source_commit"), "benchmark.source_commit")
    host = required_string(benchmark.get("host_fingerprint"), "benchmark.host_fingerprint")

    if benchmark.get("ready") is not True or benchmark.get("blockers") not in ([], None):
        blockers.append("benchmark_not_ready")
    if benchmark_manifest.get("git_commit") != source:
        blockers.append("benchmark_manifest_commit")
    if benchmark_manifest.get("host_fingerprint") != host:
        blockers.append("benchmark_manifest_host")

    large8m = benchmark_manifest.get("large8m")
    if not isinstance(large8m, dict):
        blockers.append("large8m_policy_missing")
    else:
        requested = large8m.get("requested") is True
        skip_reason = large8m.get("skip_reason")
        if not requested and (not isinstance(skip_reason, str) or not skip_reason.strip()):
            blockers.append("large8m_no_run_or_reason")

    if soak.get("ready") is not True:
        blockers.append("soak_not_ready")
    if soak.get("source_commit") != source:
        blockers.append("soak_commit")
    if soak.get("host_fingerprint") != host:
        blockers.append("soak_host")
    duration = soak.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        blockers.append("soak_duration")
        duration_value = 0.0
    else:
        duration_value = float(duration)
        if duration_value < 7200.0:
            blockers.append("soak_duration")
    if duration_value < 28800.0:
        if not eight_hour_waiver:
            blockers.append("eight_hour_soak_or_waiver")
        else:
            advisory.append("eight_hour_soak_waived")

    if staging.get("verdict") != "staging_pass":
        blockers.append("staging_not_ready")
    if staging.get("source_commit") != source:
        blockers.append("staging_commit")

    if release_evidence.get("source_commit") != source:
        blockers.append("m14_commit")
    if release_evidence.get("evidence_class") != "controlled":
        blockers.append("m14_not_controlled")
    if release_evidence.get("verdict") != "release_candidate":
        blockers.append("m14_verdict")
    if release_evidence.get("mechanics_pass") is not True:
        blockers.append("m14_mechanics")
    if release_evidence.get("blockers") not in ([], None):
        blockers.append("m14_blockers")
    raw = release_evidence.get("raw_revalidation")
    if not isinstance(raw, dict) or raw.get("valid") is not True:
        blockers.append("m14_raw_revalidation")

    controlled = release_evidence.get("controlled")
    if not isinstance(controlled, dict) or controlled.get("host_fingerprint") != host:
        blockers.append("m14_controlled_host")
    release_soak = release_evidence.get("soak")
    if not isinstance(release_soak, dict) or release_soak.get("host_fingerprint") != host:
        blockers.append("m14_soak_host")

    release_artifact = release_evidence.get("artifact")
    staging_package = staging.get("package")
    if not isinstance(release_artifact, dict) or not isinstance(staging_package, dict):
        blockers.append("artifact_identity_missing")
    else:
        release_sha = release_artifact.get("sha256")
        staging_sha = staging_package.get("sha256")
        if not isinstance(release_sha, str) or not release_sha or release_sha != staging_sha:
            blockers.append("staging_release_artifact_mismatch")

    return {
        "version": 1,
        "source_commit": source,
        "host_fingerprint": host,
        "verdict": "ready_for_manual_release" if not blockers else "blocked",
        "ready": not blockers,
        "blockers": blockers,
        "advisory": advisory,
        "strict_soak_duration_seconds": duration_value,
        "eight_hour_waiver_recorded": bool(eight_hour_waiver),
        "large8m_requested": isinstance(large8m, dict) and large8m.get("requested") is True,
        "large8m_skip_reason": large8m.get("skip_reason", "") if isinstance(large8m, dict) else "",
        "m14_verdict": release_evidence.get("verdict", ""),
        "staging_verdict": staging.get("verdict", ""),
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# M15 final release-readiness evidence",
        "",
        f"Source: `{result['source_commit']}`  ",
        f"Host fingerprint: `{result['host_fingerprint']}`  ",
        f"Verdict: **`{result['verdict']}`**  ",
        f"Strict soak: `{result['strict_soak_duration_seconds']:.1f}` s",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- `{item}`" for item in result["blockers"]) if result["blockers"] else lines.append("- none")
    lines.extend(["", "## Advisory", ""])
    lines.extend(f"- `{item}`" for item in result["advisory"]) if result["advisory"] else lines.append("- none")
    lines.extend([
        "",
        "This verdict does not create a tag or deploy production. `ready_for_manual_release` only means M15 evidence is internally consistent and the manual v0.1.0 release/canary decision may proceed.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-manifest", required=True, type=Path)
    parser.add_argument("--benchmark", required=True, type=Path)
    parser.add_argument("--soak", required=True, type=Path)
    parser.add_argument("--staging", required=True, type=Path)
    parser.add_argument("--release-evidence", required=True, type=Path)
    parser.add_argument("--eight-hour-waiver", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown", required=True, type=Path)
    args = parser.parse_args()

    waiver = None
    try:
        if args.eight_hour_waiver is not None:
            waiver = non_empty_file(args.eight_hour_waiver, "8-hour soak waiver")
        result = evaluate(
            benchmark_manifest=load_json(args.benchmark_manifest, "benchmark manifest"),
            benchmark=load_json(args.benchmark, "RC benchmark summary"),
            soak=load_json(args.soak, "RC soak linkage"),
            staging=load_json(args.staging, "staging evidence"),
            release_evidence=load_json(args.release_evidence, "M14 release evidence"),
            eight_hour_waiver=waiver,
        )
    except (M15EvidenceError, ValueError, OSError) as exc:
        print(f"M15 evidence error: {exc}")
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(result), encoding="utf-8")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
