# v0.1.0 post-release validation

Release commit:
c22867c0d643dea069dd1bc605540dfe5f1c17be

Tag:
v0.1.0

Status:
RELEASED — CONTROLLED PERFORMANCE VALIDATION PENDING

## Already validated

- normal CI;
- protocol regression;
- compatibility;
- browser tests;
- sanitizer/hardening;
- package;
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

GitHub Issue #20 (kept OPEN): https://github.com/mnevrov/nginx-grpc-web/issues/20

Remaining work items tracked there:

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
