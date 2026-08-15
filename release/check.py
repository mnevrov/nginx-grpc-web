#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from collect import EvidenceInputError, collect_bundle, git_source
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
        result = evaluate_release(bundle, policy)
        text = render_markdown(result)
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
