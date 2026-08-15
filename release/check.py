#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from collect import EvidenceInputError, collect_bundle, git_source, load_json
from evidence import ReleasePolicy, evaluate_release, render_markdown


def failure_result(release_version: str, error: str) -> dict:
    return {
        "version": 1,
        "release_version": release_version,
        "source_commit": "",
        "evidence_class": "invalid",
        "verdict": "blocked",
        "mechanics_pass": False,
        "blockers": ["input_error"],
        "advisory": [],
        "error": error,
    }


def failure_markdown(result: dict) -> str:
    return "\n".join([
        "# Release candidate evidence",
        "",
        f"Release: `{result['release_version']}`  ",
        "Evidence class: `invalid`  ",
        "Verdict: **`blocked`**",
        "",
        "## Blockers",
        "",
        "- `input_error`",
        "",
        "## Input error",
        "",
        f"`{result['error']}`",
        "",
    ])


def apply_revalidation(result: dict[str, Any], revalidation: dict[str, Any]) -> dict[str, Any]:
    output = dict(result)
    output["blockers"] = list(result.get("blockers", []))
    output["advisory"] = list(result.get("advisory", []))
    output["raw_revalidation"] = dict(revalidation)

    evidence_class = str(output.get("evidence_class", ""))
    if evidence_class == "controlled":
        if revalidation.get("valid") is not True:
            if "raw_revalidation" not in output["blockers"]:
                output["blockers"].append("raw_revalidation")
    else:
        if revalidation.get("valid") is False:
            if "raw_revalidation" not in output["blockers"]:
                output["blockers"].append("raw_revalidation")
        elif revalidation.get("skipped") != "harness_only":
            if "revalidation_not_harness_only" not in output["blockers"]:
                output["blockers"].append("revalidation_not_harness_only")

    output["mechanics_pass"] = not output["blockers"]
    if output["blockers"]:
        output["verdict"] = "blocked"
    elif evidence_class == "controlled":
        output["verdict"] = "release_candidate"
    else:
        output["verdict"] = "inconclusive"
    return output


def render_with_revalidation(result: dict[str, Any]) -> str:
    text = render_markdown(result)
    raw = result.get("raw_revalidation", {})
    lines = [text.rstrip(), "", "## Raw evidence revalidation", ""]
    if raw.get("valid") is True:
        lines.append("- controlled capacity/decision and strict soak aggregates were recomputed from raw evidence and matched")
    elif raw.get("skipped") == "harness_only":
        lines.append("- skipped intentionally for `harness_only` CI mechanics evidence")
    else:
        lines.append(f"- invalid: `{raw.get('error', 'unknown revalidation state')}`")
    lines.append("")
    return "\n".join(lines)


def write_result(output: Path, markdown: Path, result: dict, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--release-version", default="v0.1.0")
    parser.add_argument("--nginx-version", default="1.30.4")
    parser.add_argument("--compiler", default="gcc")
    parser.add_argument("--gates", required=True, type=Path)
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--controlled-dir", required=True, type=Path)
    parser.add_argument("--soak-dir", required=True, type=Path)
    parser.add_argument("--revalidation", required=True, type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown", required=True, type=Path)
    parser.add_argument("--allow-inconclusive", action="store_true")
    args = parser.parse_args()

    try:
        policy = ReleasePolicy(
            release_version=args.release_version,
            nginx_version=args.nginx_version,
            compiler=args.compiler,
        )
        if args.policy is not None:
            policy = ReleasePolicy.from_dict(json.loads(args.policy.read_text(encoding="utf-8")))
        source = git_source(args.repo_root)
        bundle = collect_bundle(
            release_version=args.release_version,
            source=source,
            gates_path=args.gates,
            package_dir=args.package_dir,
            controlled_dir=args.controlled_dir,
            soak_dir=args.soak_dir,
        )
        revalidation = load_json(args.revalidation, "raw evidence revalidation")
        result = apply_revalidation(evaluate_release(bundle, policy), revalidation)
        text = render_with_revalidation(result)
    except (EvidenceInputError, ValueError, OSError, json.JSONDecodeError) as exc:
        result = failure_result(args.release_version, str(exc))
        text = failure_markdown(result)

    write_result(args.output, args.markdown, result, text)
    if result["verdict"] == "release_candidate":
        return 0
    if args.allow_inconclusive and result["verdict"] == "inconclusive" and result["mechanics_pass"]:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
