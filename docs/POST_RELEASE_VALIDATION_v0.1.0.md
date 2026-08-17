# v0.1.0 post-release validation

Release line:
`v0.1.0`

Source identity:
The authoritative release source is the commit referenced by the published `v0.1.0` Git tag. Do not infer the final tag target from an earlier milestone SHA recorded in this document.

M15 code baseline:
`c22867c0d643dea069dd1bc605540dfe5f1c17be` (merge of PR #21).

Release metadata was merged after the M15 code baseline (PR #22 and subsequent provenance-only release-prep changes), so the final tag target is intentionally resolved only at publication time from the then-current, green `main`.

Status:
CONTROLLED PERFORMANCE VALIDATION PENDING

## Already validated

- normal CI;
- protocol regression;
- compatibility;
- browser tests;
- sanitizer/hardening;
- package mechanics;
- M14 mechanics;
- M15 tooling mechanics.

## Deferred

- dedicated controlled host benchmark;
- capacity boundaries;
- five repeat campaign;
- 2h soak;
- 8h soak;
- staging;
- Envoy rollback.

## Evidence policy

Any CI/shared-runner smoke data (including prior M9–M13 numeric observations) remains classified

```text
evidence_class = harness_only
```

and cannot be promoted to `controlled` evidence. `harness_only` results must not be cited as production capacity, performance delta, or benchmark claims. Only evidence produced by the M15 controlled-host tooling (`perf/rc.py`, `perf/rc_soak.py`, `staging/evidence.py`, `release/m15.py`) against a dedicated, non-shared host with strict preflight can be classified `controlled`.

## Tracking

GitHub Issue #20 remains OPEN and tracks post-release controlled validation:
https://github.com/mnevrov/nginx-grpc-web/issues/20

Remaining work items:

1. controlled typical 4 KiB capacity;
2. controlled 4 MiB;
3. slow consumer;
4. 8 MiB or documented rationale;
5. >=5 repeats;
6. >=2h strict soak;
7. recommended 8h soak;
8. real staging acceptance;
9. practical Envoy rollback;
10. final M14/M15 controlled evidence (`ready_for_manual_release`).
