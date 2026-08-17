# M15 — Controlled-host RC benchmark & staging acceptance

## Mission

Turn the M9–M14 benchmark/evidence machinery into the first release-quality quantitative comparison of:

```text
legacy: loadgen -> NGINX -> Envoy -> native gRPC backend
native: loadgen -> NGINX + ngx_http_grpc_web_module -> native gRPC backend
```

M15 must measure a real capacity boundary on controlled hardware. Shared CI is useful only for mechanics and must never be promoted to controlled evidence.

## Dependency

This branch is stacked on M14. Until M14 is merged, M15 remains dependent work. Final release evidence must later be regenerated from the eventual exact release commit in `main`.

## Scope freeze

Do not add client streaming, bidi streaming, grpc-web JSON, CORS/auth/routing/retries/service discovery, custom upstream HTTP/2 transport, or unrelated production C changes.

If controlled testing discovers a production defect, isolate it in a dedicated regression-first fix and document why it blocks release.

## Primary deliverables

1. One operator entry point (`make rc-benchmark` or equivalent).
2. Strict preflight before expensive work.
3. Controlled TLS/H2 typical, large-payload and slow-consumer scenarios.
4. A real sustainable-capacity boundary for both architectures, not a bounded smoke lower bound.
5. Five strict repeats per selected scenario attempt.
6. Preserved raw artifacts and host fingerprint.
7. Machine-readable/human-readable M15 summary.
8. Mandatory >=2h strict soak workflow and documented 8h RC run.
9. Staging acceptance procedure with the real React/`grpc-web` client and practical Envoy rollback.
10. Feed final controlled artifacts into M14 `make release-check` without weakening any M14 gate.

## Benchmark rules

### Host isolation

Reuse `perf/host_info.py` and M12 strict semantics. Required:

- Linux cgroup v2;
- explicit gateway/backend/loadgen CPU sets;
- all CPU sets online;
- no overlap;
- stable host fingerprint;
- same NGINX/compiler target across all evidence.

Warnings such as an unavailable/non-performance CPU governor must be preserved, not silently discarded.

### Transport

Primary frontend is `tls-h2`. The load generator must observe valid TLS and HTTP/2 with ALPN `h2`; silent fallback is a hard failure.

### Capacity boundary

The benchmark must not report a final capacity delta if either architecture has only a lower bound (`first_failed_streams == null`).

Start typical runs with a useful staircase such as:

```text
25,50,100,200,400,800,1200
```

If both boundaries are not reached, extend the staircase deterministically and run another complete controlled attempt. Preserve every attempt. Never splice partial repeat sets together.

Use a bounded maximum stream count/attempt count and fail closed with a clear `boundary_not_reached` reason if the configured ceiling is exhausted.

### Scenarios

At minimum:

- typical grpc-web-text: 4 KiB DATA;
- large text: 4 MiB DATA;
- large 8 MiB when target hardware permits;
- binary large-payload diagnostic baseline where useful;
- slow-consumer/backpressure.

SLO thresholds are service/environment inputs. Do not invent production SLO values inside the code. The operator must supply explicit SLO JSON files.

### Repeats

Release-quality selected attempt: minimum five strict repeats. Preserve all `repeat-NN` raw JSON and stats.

### Decision

Reuse M11 `capacity.py` and M12 `decision.py`; do not implement a second performance interpretation engine.

The M15 summary should expose, for each scenario:

- source SHA;
- host fingerprint;
- SLO identity;
- repeat count;
- capacity min/median/max/CV for legacy/native;
- capacity delta;
- conservative same-load reference streams;
- p99 TTFD delta;
- p99 backend-to-client delta;
- gateway CPU delta;
- peak RSS delta;
- error-rate delta;
- evidence class;
- recommendation/reasons;
- whether real boundaries were observed in every repeat.

## Soak

The selected release host must also pass the M13 strict soak policy:

- >=7200 s mandatory;
- >=28800 s recommended RC evidence;
- valid strict host preflight;
- bounded RSS slope/growth;
- steady/churn/cancel accounting;
- hard backend disruption observed + recovery;
- transport resets accounted + recovery;
- final healthy probe;
- unchanged NGINX master PID and container restart count.

Do not attempt to fake long runs in CI.

## Staging

Use the packaged `.so` installed the same way as production. Validate with the actual React/`grpc-web` client:

- binary unary;
- text unary;
- incremental server streaming;
- non-zero status/message;
- cancellation;
- deadline;
- unavailable/timeout normalization;
- long stream memory behavior;
- saved `nginx -T`;
- tested rollback to Envoy.

## Failure-closed requirements

Reject or leave inconclusive:

- dirty source tree;
- missing/invalid strict preflight;
- mixed host fingerprints;
- fewer than five release repeats;
- missing capacity artifacts;
- either architecture without an observed first failing capacity level;
- mismatched scenario parameters;
- shared CI / `harness_only` evidence;
- missing SLO input;
- malformed reports;
- exhausted boundary-search ceiling;
- failed soak/staging gates.

## Test strategy

Keep orchestration logic as pure/testable Python where possible. Unit tests must cover at least:

- both boundaries reached;
- legacy boundary missing;
- native boundary missing;
- mixed host fingerprint;
- harness-only result;
- too few repeats;
- malformed/missing capacity files;
- deterministic staircase extension and maximum ceiling;
- aggregate summary across multiple scenarios.

CI may exercise synthetic fixtures and a very small harness-only run, but must assert that it cannot produce release-quality controlled evidence.

## Exit

M15 code can merge when its mechanics are green. Actual release completion additionally requires real controlled-host artifacts, >=2h strict soak, staging acceptance, M14 `controlled/release_candidate` evidence, and then a manual tag/release decision.
