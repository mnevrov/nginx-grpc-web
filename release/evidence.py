#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REQUIRED_GATES = ("compatibility", "protocol", "differential", "browser", "hardening")
VALID_EVIDENCE_CLASSES = {"controlled", "harness_only"}


@dataclass(frozen=True)
class ReleasePolicy:
    release_version: str = "v0.1.0"
    nginx_version: str = "1.30.4"
    compiler: str = "gcc"
    min_strict_soak_seconds: float = 7200.0
    recommended_rc_soak_seconds: float = 28800.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReleasePolicy":
        if not isinstance(data, dict):
            raise ValueError("release policy must be an object")
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"unknown release policy fields: {', '.join(unknown)}")
        policy = cls(**data)
        policy.validate()
        return policy

    def validate(self) -> None:
        for name in ("release_version", "nginx_version", "compiler"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in ("min_strict_soak_seconds", "recommended_rc_soak_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be a finite number")
        if float(self.min_strict_soak_seconds) <= 0:
            raise ValueError("min_strict_soak_seconds must be > 0")
        if float(self.recommended_rc_soak_seconds) < float(self.min_strict_soak_seconds):
            raise ValueError("recommended_rc_soak_seconds must be >= min_strict_soak_seconds")


def _dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _non_empty(value: Any) -> str:
    return str(value or "").strip()


def _append_once(items: list[str], reason: str) -> None:
    if reason not in items:
        items.append(reason)


def _report_commit_matches(manifest: dict[str, Any], source_commit: str) -> bool:
    return _non_empty(manifest.get("git_commit")) == source_commit


def _sha256_shape(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _duration_seconds(value: Any, blockers: list[str]) -> float:
    if isinstance(value, bool):
        _append_once(blockers, "soak_duration_value")
        return 0.0
    try:
        duration = float(value)
    except (TypeError, ValueError):
        _append_once(blockers, "soak_duration_value")
        return 0.0
    if not math.isfinite(duration) or duration < 0:
        _append_once(blockers, "soak_duration_value")
        return 0.0
    return duration


def evaluate_release(bundle: dict[str, Any], policy: ReleasePolicy) -> dict[str, Any]:
    """Apply deterministic cross-document provenance and release policy rules."""

    policy.validate()
    bundle = _dict(bundle, "bundle")
    source = _dict(bundle.get("source"), "source")
    gates = _dict(bundle.get("gates"), "gates")
    artifact = _dict(bundle.get("artifact"), "artifact")
    controlled = _dict(bundle.get("controlled"), "controlled")
    soak = _dict(bundle.get("soak"), "soak")

    blockers: list[str] = []
    advisory: list[str] = []

    version = _non_empty(bundle.get("release_version"))
    if version != policy.release_version:
        _append_once(blockers, "release_version")

    source_commit = _non_empty(source.get("commit"))
    if not source_commit or source_commit == "unknown":
        _append_once(blockers, "source_commit")
    dirty = source.get("dirty")
    if dirty is not False:
        _append_once(blockers, "dirty_tree" if dirty is True else "source_dirty_state")

    gate_summary: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_GATES:
        gate = gates.get(name)
        if not isinstance(gate, dict):
            _append_once(blockers, f"gate_{name}_missing")
            gate_summary[name] = {"passed": False, "commit": "", "evidence_class": ""}
            continue
        raw_passed = gate.get("passed")
        passed = raw_passed is True
        commit = _non_empty(gate.get("commit"))
        raw_gate_class = gate.get("evidence_class")
        gate_class = raw_gate_class if isinstance(raw_gate_class, str) else ""
        gate_summary[name] = {"passed": passed, "commit": commit, "evidence_class": gate_class}
        if raw_passed not in (True, False) or not isinstance(raw_passed, bool):
            _append_once(blockers, f"gate_{name}_invalid")
        elif not passed:
            _append_once(blockers, f"gate_{name}_failed")
        if gate_class not in VALID_EVIDENCE_CLASSES:
            _append_once(blockers, f"gate_{name}_evidence_class")
        if source_commit and commit != source_commit:
            _append_once(blockers, f"gate_{name}_commit")

    declared_sha = _non_empty(artifact.get("declared_sha256")).lower()
    actual_sha = _non_empty(artifact.get("actual_sha256")).lower()
    if not declared_sha or not actual_sha:
        _append_once(blockers, "artifact_checksum_missing")
    else:
        if not _sha256_shape(declared_sha) or not _sha256_shape(actual_sha):
            _append_once(blockers, "artifact_checksum_format")
        if declared_sha != actual_sha:
            _append_once(blockers, "artifact_checksum_mismatch")

    artifact_manifest = _dict(artifact.get("manifest"), "artifact.manifest")
    artifact_commit = _non_empty(artifact_manifest.get("source_commit"))
    artifact_nginx = _non_empty(artifact_manifest.get("nginx_version"))
    artifact_compiler = _non_empty(artifact_manifest.get("compiler"))
    artifact_platform = _non_empty(artifact_manifest.get("platform"))
    artifact_build_mode = _non_empty(artifact_manifest.get("build_mode"))
    artifact_module = _non_empty(artifact_manifest.get("module"))
    if source_commit and artifact_commit != source_commit:
        _append_once(blockers, "artifact_commit")
    if artifact_nginx != policy.nginx_version:
        _append_once(blockers, "artifact_nginx_version")
    if artifact_compiler != policy.compiler:
        _append_once(blockers, "artifact_compiler")
    if artifact_build_mode != "--with-compat":
        _append_once(blockers, "artifact_build_mode")
    if not artifact_platform:
        _append_once(blockers, "artifact_platform")
    if artifact_module != "ngx_http_grpc_web_module.so":
        _append_once(blockers, "artifact_module")

    controlled_manifest = _dict(controlled.get("manifest"), "controlled.manifest")
    decision = _dict(controlled.get("decision"), "controlled.decision")
    controlled_commit = _non_empty(controlled_manifest.get("git_commit"))
    controlled_nginx = _non_empty(controlled_manifest.get("nginx_version"))
    controlled_compiler = _non_empty(controlled_manifest.get("build_cc"))
    if source_commit and controlled_commit != source_commit:
        _append_once(blockers, "controlled_commit")
    if controlled_nginx != policy.nginx_version:
        _append_once(blockers, "controlled_nginx_version")
    if controlled_compiler != policy.compiler:
        _append_once(blockers, "controlled_compiler")

    soak_manifest = _dict(soak.get("manifest"), "soak.manifest")
    soak_report = _dict(soak.get("report"), "soak.report")
    soak_commit = _non_empty(soak_manifest.get("git_commit"))
    soak_nginx = _non_empty(soak_manifest.get("nginx_version"))
    soak_compiler = _non_empty(soak_manifest.get("build_cc"))
    if source_commit and soak_commit != source_commit:
        _append_once(blockers, "soak_commit")
    if soak_nginx != policy.nginx_version:
        _append_once(blockers, "soak_nginx_version")
    if soak_compiler != policy.compiler:
        _append_once(blockers, "soak_compiler")

    decision_class = _non_empty(decision.get("evidence_class"))
    soak_class = _non_empty(soak_report.get("evidence_class"))
    if decision_class not in VALID_EVIDENCE_CLASSES:
        _append_once(blockers, "controlled_evidence_class")
    if soak_class not in VALID_EVIDENCE_CLASSES:
        _append_once(blockers, "soak_evidence_class")
    evidence_class = "controlled" if decision_class == "controlled" and soak_class == "controlled" else "harness_only"

    if evidence_class == "controlled":
        for name in REQUIRED_GATES:
            if gate_summary[name]["evidence_class"] != "controlled":
                _append_once(blockers, f"gate_{name}_evidence_class")

    controlled_host = _non_empty(decision.get("host_fingerprint"))
    soak_events = soak_report.get("events")
    soak_events = soak_events if isinstance(soak_events, dict) else {}
    soak_host_record = soak_events.get("host")
    soak_host_record = soak_host_record if isinstance(soak_host_record, dict) else {}
    soak_host = _non_empty(soak_host_record.get("fingerprint"))

    if evidence_class == "controlled":
        if not controlled_host or not soak_host or controlled_host != soak_host:
            _append_once(blockers, "host_fingerprint")
        if soak_manifest.get("strict") is not True:
            _append_once(blockers, "soak_not_strict")
        if soak_host_record.get("strict") is not True or soak_host_record.get("valid") is not True:
            _append_once(blockers, "soak_host_preflight")
    else:
        _append_once(advisory, "harness_only")

    if decision_class == "controlled" and _non_empty(decision.get("recommendation")) != "native_preferred":
        _append_once(blockers, "controlled_decision")

    duration = _duration_seconds(soak_report.get("duration_seconds", 0.0), blockers)
    if soak_class == "controlled":
        if _non_empty(soak_report.get("verdict")) != "soak_pass":
            _append_once(blockers, "soak_verdict")
        if duration < float(policy.min_strict_soak_seconds):
            _append_once(blockers, "soak_duration")
        if duration < float(policy.recommended_rc_soak_seconds):
            _append_once(advisory, "rc_soak_8h_recommended")

    mechanics_pass = not blockers
    if blockers:
        verdict = "blocked"
    elif evidence_class != "controlled":
        verdict = "inconclusive"
    else:
        verdict = "release_candidate"

    return {
        "version": 1,
        "release_version": version,
        "source_commit": source_commit,
        "evidence_class": evidence_class,
        "verdict": verdict,
        "mechanics_pass": mechanics_pass,
        "blockers": blockers,
        "advisory": advisory,
        "policy": asdict(policy),
        "gates": gate_summary,
        "artifact": {
            "module": artifact_module,
            "sha256": actual_sha,
            "source_commit": artifact_commit,
            "nginx_version": artifact_nginx,
            "compiler": artifact_compiler,
            "platform": artifact_platform,
            "build_mode": artifact_build_mode,
        },
        "controlled": {
            "source_commit": controlled_commit,
            "nginx_version": controlled_nginx,
            "compiler": controlled_compiler,
            "evidence_class": decision_class,
            "recommendation": _non_empty(decision.get("recommendation")),
            "host_fingerprint": controlled_host,
        },
        "soak": {
            "source_commit": soak_commit,
            "nginx_version": soak_nginx,
            "compiler": soak_compiler,
            "strict": soak_manifest.get("strict") is True,
            "evidence_class": soak_class,
            "verdict": _non_empty(soak_report.get("verdict")),
            "duration_seconds": duration,
            "host_fingerprint": soak_host,
        },
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Release candidate evidence",
        "",
        f"Release: `{result['release_version']}`  ",
        f"Source commit: `{result['source_commit']}`  ",
        f"Evidence class: `{result['evidence_class']}`  ",
        f"Verdict: **`{result['verdict']}`**  ",
        f"Mechanics pass: `{str(result['mechanics_pass']).lower()}`",
        "",
        "## Gates",
        "",
        "| gate | passed | class | commit |",
        "|---|---|---|---|",
    ]
    for name in REQUIRED_GATES:
        gate = result["gates"][name]
        lines.append(
            f"| `{name}` | `{str(gate['passed']).lower()}` | `{gate['evidence_class']}` | `{gate['commit']}` |"
        )

    lines.extend([
        "",
        "## Artifact",
        "",
        f"- module: `{result['artifact']['module']}`",
        f"- SHA256: `{result['artifact']['sha256']}`",
        f"- source commit: `{result['artifact']['source_commit']}`",
        f"- NGINX: `{result['artifact']['nginx_version']}`",
        f"- compiler: `{result['artifact']['compiler']}`",
        f"- platform: `{result['artifact']['platform']}`",
        f"- build mode: `{result['artifact']['build_mode']}`",
        "",
        "## Controlled evidence",
        "",
        f"- source commit: `{result['controlled']['source_commit']}`",
        f"- NGINX/compiler: `{result['controlled']['nginx_version']}` / `{result['controlled']['compiler']}`",
        f"- class: `{result['controlled']['evidence_class']}`",
        f"- recommendation: `{result['controlled']['recommendation']}`",
        f"- host fingerprint: `{result['controlled']['host_fingerprint']}`",
        "",
        "## Soak evidence",
        "",
        f"- source commit: `{result['soak']['source_commit']}`",
        f"- NGINX/compiler: `{result['soak']['nginx_version']}` / `{result['soak']['compiler']}`",
        f"- strict: `{str(result['soak']['strict']).lower()}`",
        f"- class: `{result['soak']['evidence_class']}`",
        f"- verdict: `{result['soak']['verdict']}`",
        f"- duration: `{result['soak']['duration_seconds']:.1f}` s",
        f"- host fingerprint: `{result['soak']['host_fingerprint']}`",
        "",
        "## Blockers",
        "",
    ])
    lines.extend(f"- `{reason}`" for reason in result["blockers"]) if result["blockers"] else lines.append("- none")
    lines.extend(["", "## Advisory", ""])
    lines.extend(f"- `{reason}`" for reason in result["advisory"]) if result["advisory"] else lines.append("- none")
    lines.extend([
        "",
        "`release_candidate` means the machine-checkable M14 evidence is internally consistent. It is not permission to tag or deploy: staging acceptance, manual release publication and canary/rollback remain separate gates.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown", required=True, type=Path)
    parser.add_argument("--allow-inconclusive", action="store_true")
    args = parser.parse_args()

    policy = ReleasePolicy()
    if args.policy is not None:
        policy = ReleasePolicy.from_dict(json.loads(args.policy.read_text(encoding="utf-8")))
    bundle = json.loads(args.input.read_text(encoding="utf-8"))
    result = evaluate_release(bundle, policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(result), encoding="utf-8")

    if result["verdict"] == "release_candidate":
        return 0
    if args.allow_inconclusive and result["verdict"] == "inconclusive" and result["mechanics_pass"]:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
