# Implementation Plan

Работа идёт маленькими проверяемыми этапами.

## M0 — Test oracle and harness ✅

- deterministic gRPC backend;
- Envoy reference route;
- canonical gRPC-Web decoder in tests;
- React/grpc-web browser smoke;
- reference tests green.

**Exit:** Envoy path полностью воспроизводим локально и в CI.

## M1 — Module skeleton ✅

- dynamic module builds for supported NGINX;
- `grpc_web on|off`;
- activation only for grpc-web content types;
- no behavior changes when off.

**Exit:** compile/config smoke green.

## M2 — Binary unary ✅

- request header adaptation;
- binary body passthrough;
- response media type;
- native trailers -> grpc-web trailer frame.

**Exit:** binary unary differential + browser test green.

## M3 — Text unary request ✅

- incremental base64 request decoder;
- arbitrary fragmentation;
- malformed input handling;
- content-length correctness.

**Exit:** text unary differential tests green.

## M4 — Text unary response ✅

- incremental/semantic base64 output;
- trailer frame encode;
- non-zero status/message.

**Exit:** unary text browser tests green.

## M5 — Server streaming ✅

- incremental response without whole-stream buffering;
- fragmented gRPC frames across NGINX upstream buffers;
- slow backend with observable inter-message timing;
- same React/grpc-web text streaming client through Envoy and NGINX;
- first browser `data` event before RPC completion;
- trailers after multiple DATA frames;
- slow-client/backpressure regression;
- long-stream memory regression;
- reusable native-frame scratch buffer;
- reusable Base64 output via NGINX `free`/`busy` chains.

**Exit:** timing/browser/differential tests green, slow consumer green, long-stream RSS delta stays below the regression gate instead of scaling with total stream bytes.

### M5 memory finding

Initial streaming tests showed that M4 was already timing-correct: completed gRPC frames were flushed to the browser incrementally. Stress testing then exposed request-pool retention: the old per-frame allocation strategy increased NGINX RSS by **70.2 MiB** while producing about 40 MiB of gRPC-Web text during one long stream.

M5 fixes the lifetime model rather than weakening the test:

- current native frame storage is reused and only grows to required maximum capacity;
- encoded response buffers are tagged and recycled with `ngx_chain_update_chains()`;
- a 480-frame stress stream is required to stay under a `<32 MiB` peak RSS delta gate;
- slow-consumer and wire-semantics tests run together with the RSS regression.

## M6 — Cancellation and failures ✅

- clean empty stream;
- application-level mid-stream gRPC abort after one or more DATA frames;
- `grpc-timeout` / `DEADLINE_EXCEEDED`;
- browser `cancel()` / downstream disconnect propagated to native upstream RPC;
- dead upstream / connect failure;
- proxy-side read timeout before first DATA;
- local NGINX `502/503` normalized to terminal `UNAVAILABLE (14)` for grpc-web requests;
- local NGINX `504/408` normalized to terminal `DEADLINE_EXCEEDED (4)` for grpc-web requests;
- standard NGINX HTML error body removed from normalized grpc-web local errors;
- synthetic local-error response validated as `HTTP 200 + grpc-web content-type + one terminal trailer frame`;
- observable React error codes compared with Envoy;
- browser harness records synchronous `data/error/status/end` event trace so terminal semantics are not hidden by React batching.

**Exit:** protocol/wire/browser failure matrix green; existing React `grpc-web` client observes matching Envoy status semantics for the covered gateway failures.

### M6 implementation finding

The test-first pass showed that empty streams, application gRPC aborts, deadlines and cancellation already worked through stock `ngx_http_grpc_module`; no production-module change was needed for those paths.

The actual compatibility gap was local NGINX gateway errors. A dead upstream produced ordinary HTML `502`, and a proxy read timeout produced HTML `504`; the browser `grpc-web` client mapped both to `UNKNOWN (2)`. M6 introduces a deliberately narrow local-error adapter only after the request has already been recognized as grpc-web.

The application mid-stream test uses a valid gRPC terminal status (`context.abort()`), not a raw transport failure. HTTP/2 `RST_STREAM` / TCP reset after DATA remains a separate M7 fault-injection case.

## M7 — Hardening ✅

- exact activation only for the four supported v0.1 media-type tokens;
- optional media-type parameters after `;` supported without accepting lookalike suffixes;
- `+json`, `+protoevil` and arbitrary prefix/suffix variants remain outside module scope;
- ASAN/UBSAN gate for pure C Base64/frame state machines;
- libFuzzer targets for incremental Base64 and gRPC frame parser, `20 000` bounded runs each in CI;
- raw HTTP/2 fault backend independent of the gRPC framework;
- `RST_STREAM` before response headers compared with Envoy through the real React/`grpc-web` client;
- `RST_STREAM` and TCP reset after completed DATA verify DATA preservation and bounded lifecycle;
- oversized native frame declaration rejected before scratch-buffer memory amplification;
- truncated native frame / incomplete EOF cannot poison worker state;
- DATA followed by HTTP/2 EOF without native gRPC trailers cannot become false `grpc-status: 0`;
- repeated after-DATA transport faults gated by `<16 MiB` RSS delta;
- repeated downstream disconnect/cancellation stress gated by `<16 MiB` RSS delta;
- malformed request/logging regression verifies that request payload and `Authorization` secrets are not written to NGINX logs.

**Exit:** sanitizer/fuzz/fault-injection suite green; supported parser and streaming paths have no known unbounded-memory, false-success, media-type-confusion or transport-reset lifecycle defect.

### M7 media-type finding

The initial hardening regression exposed a real production bug: content type detection used prefix comparison, so `application/grpc-web+json`, `application/grpc-web+protoevil` and similar values activated the module. The production change in M7 is deliberately narrow: exact token matching for the four supported media types, with optional parameters handled after `;`.

### M7 transport-reset finding

A raw upstream transport reset is not equivalent to a valid application-level gRPC failure. In particular, when the HTTP/2 fault backend sends one completed DATA frame and then `RST_STREAM`, the Envoy reference delivers that DATA to the browser but may leave the `grpc-web` RPC in `running` without a synthetic terminal `error/status/end` event.

Therefore M7 does **not** invent a stronger terminal contract for NGINX than the oracle provides:

- reset before DATA/headers: compare observable browser error semantics with Envoy;
- reset after completed DATA: require byte-exact DATA preservation, bounded memory/lifecycle and a healthy next request;
- missing native trailers: never synthesize false `grpc-status: 0`.

This distinction keeps the test oracle semantic rather than accidentally encoding an implementation-specific expectation.

## M8 — Compatibility & rollout ✅

- compatibility matrix moved to current NGINX stable `1.30.4` and mainline `1.31.3`;
- previous `1.30.2 / 1.31.1` targets retired from production guidance because later NGINX security releases include a fix affecting `ngx_http_grpc_module`;
- dynamic module builds on both NGINX lines with GCC and Clang;
- build gate performs real `load_module` validation through `nginx -t`, not only compilation;
- full protocol/hardening/differential suite runs on stable and mainline;
- real React/`grpc-web` browser suite is split across Chromium, Firefox and WebKit on stable;
- Docker `module-artifact` target and `make package-module` produce versioned `.so` directory with SHA256 and manifest;
- CI package smoke verifies the artifact and stores it as a short-lived Actions artifact;
- production configuration example added under `examples/`;
- compatibility/installation/observability guidance added;
- Envoy -> NGINX canary and rollback procedure added;
- v0.1 release checklist and binary-artifact contract added;
- PR CI now cancels superseded runs so only the latest head consumes the full compatibility matrix.

**Exit:** supported build/runtime matrix documented and green; operators have a reproducible installation, migration, verification and rollback procedure for v0.1.

### M8 compatibility finding

Compatibility is deliberately defined narrower than “a `.so` loads everywhere”. Prebuilt artifacts are tagged with exact NGINX version, compiler, platform and source commit. The Docker-produced binary is validated against the matching official `nginx:<version>` image. Existing distro/vendor NGINX installations must be checked with `nginx -V`; if ABI compatibility is uncertain, the module is rebuilt on the target platform instead of assuming portability.

### M8 rollout model

Canary traffic is recommended between independent legacy and native gateway pools:

```text
                         +-> legacy gateway -> Envoy -> backend
browser -> LB / ingress -|
                         +-> native gateway -> NGINX module -> backend
```

This keeps rollback independent from the frontend and reduces it to routing weight change. Envoy should remain warm for an agreed rollback window after reaching 100% native traffic.

## M9 — Server-streaming performance engine ✅

- Go grpc-web load generator for concurrent server-side streams;
- incremental text decoder supports independently padded Base64 blocks and arbitrary HTTP fragmentation;
- binary grpc-web mode retained as Base64-cost diagnostic baseline;
- deterministic backend can generate 1/4/8 MiB DATA without a matching multi-MiB request body;
- benchmark-only backend-relative `server_elapsed_ns` timing captured immediately before response yield;
- A/B topology keeps the same front NGINX version/worker count for both architectures;
- legacy path disables proxy request/response buffering to avoid artificial disadvantage;
- `typical`, `large` and `slow` profiles;
- A/B/B/A ordering for measured sweeps;
- cgroup v2 cumulative CPU sampling;
- process `VmRSS` separated from `memory.current`;
- JSON raw results and Markdown/JSON aggregation;
- CI `perf-loadgen` protocol/unit gate and real `perf-smoke` topology gate;
- shared GitHub runner explicitly treated as harness validation only.

**Exit:** loadgen protocol gate and real A/B topology smoke green; both paths produce valid streams, resource samples and machine-readable reports without making an unsupported performance claim from shared-runner numbers.

### M9 measurement finding

The first resource sampler used `docker stats`, which produced no samples on very short CI runs. M9 replaced it with host-side cgroup v2 cumulative counters and explicit process RSS sampling. Report generation now fails when a measured run has fewer than two resource samples rather than publishing misleading zero CPU/RSS values.

## M10 — Production-like TLS/HTTP2 performance path ✅

- identical TLS listeners are added to legacy/native front NGINX while preserving the existing cleartext HTTP/1.1 baseline;
- NGINX enables HTTP/2 through `http2 on;` and the same TLS policy on both paths;
- ephemeral benchmark CA/server certificate is generated locally and never committed;
- CA private key is deleted after server certificate signing;
- loadgen accepts a benchmark CA and optional TLS server-name override;
- custom TLS transport explicitly attempts HTTP/2;
- `tls-h2` runs require `response.ProtoMajor == 2`, TLS state and ALPN `h2`;
- silent HTTP/1.1 fallback is a failed sample;
- negotiated HTTP protocol, TLS version and ALPN are stored per stream;
- `frontend` becomes part of report scenario identity so HTTP/1.1 and TLS/H2 samples cannot be aggregated together;
- `perf-h2-smoke`, `perf-h2-typical`, `perf-h2-large`, `perf-h2-slow` mirror the existing profiles;
- dedicated CI TLS/H2 topology gate validates every raw stream as HTTP/2 over TLS.

**Exit:** strict TLS/H2 unit and topology gates green on exact PR head; HTTP/1.1 baseline remains green; existing module/browser/integration/hardening matrix is unchanged; no production module C behavior is modified.

### M10 interpretation rule

TLS/H2 results are a production-like transport baseline, not literal browser certification. Browser compatibility continues to come from the real React/`grpc-web` Playwright matrix. Performance conclusions must compare legacy/native within the same frontend mode and should be produced on controlled hardware with repeated A/B/B/A runs.

## M11 — Capacity / SLO staircase ✅

- SLO-driven capacity evaluator over existing M9/M10 report data;
- supported limits: error rate, p99 backend-to-client, p99 TTFD, average gateway cores and peak RSS;
- capacity defined as the highest contiguous passing concurrency from the lowest staircase level;
- a later accidental pass after the first failure cannot increase sustainable capacity;
- A/B/B/A repeated on every concurrency step;
- automatic early stop when both architectures fail the current SLO step;
- separate HTTP/1 and TLS/H2 capacity targets;
- explicit `PERF_CAPACITY_SLO` required for production-style runs;
- optional equal CPU-set budget through `PERF_GATEWAY_CPUSET`;
- legacy NGINX + Envoy share that CPU set instead of receiving separate hidden CPU budgets;
- `capacity.json` + `capacity.md` outputs;
- CI mechanics gate for both `http1` and `tls-h2`;
- CI smoke limits intentionally broad and explicitly not production capacity evidence;
- controlled-host methodology documented in `docs/CAPACITY_BENCHMARKS.md`.

**Exit:** SLO classifier tests green; both HTTP/1 and strict TLS/H2 capacity topology smoke gates green; exact CI matrix green; no production module C behavior changed.

### M11 capacity rule

`max_sustainable_streams` is meaningful only when derived from a monotonic tested staircase under one fixed SLO and resource budget. If `first_failed_streams` is `null`, the capacity boundary was not reached and the staircase must continue. Shared GitHub runner values validate the harness only; architecture claims require controlled-host repeated runs.

## M12 — Controlled-host benchmark decision ✅

- strict host preflight built on Linux cgroup v2;
- explicit non-overlapping gateway/backend/loadgen CPU sets;
- validation that configured CPUs are online;
- stable host fingerprint excludes timestamp/hostname noise but captures kernel, CPU, RAM, Docker/cgroup and CPU allocation;
- complete M11 capacity staircase repeated independently;
- minimum repeat count defined by decision policy;
- legacy/native sustainable capacity aggregated as min/median/max/CV;
- architecture comparison uses the conservative common sustainable load instead of comparing resource usage at different concurrencies;
- p99 TTFD, p99 backend-to-client latency, CPU, RSS and error deltas aggregated across repeats;
- `decision.json` + `decision.md` outputs;
- shared GitHub runner forced to `harness_only/inconclusive`, regardless of favorable deltas;
- typical, 4 MiB/8 MiB DATA and slow-consumer controlled-run methodology documented.

**Exit:** repeated TLS/H2 controlled workflow mechanics green; mixed hosts and unstable repeats are rejected; only strict controlled evidence can produce `native_preferred`; no production module C behavior changed.

### M12 evidence rule

Performance numbers from shared CI are never architecture evidence. A decision requires one stable controlled host configuration, isolated CPU budgets, repeated complete staircases and bounded variance. Raw per-repeat artifacts are preserved next to the aggregate decision.

## M13 — Server-streaming soak / production readiness 🚧

- Go loadgen supports deterministic expected client cancellation after N DATA frames;
- cancellation is counted separately from successful completion and cannot mask unexpected errors;
- one TLS/H2 native NGINX master/worker remains alive for the entire soak;
- continuous cgroup-v2 process RSS and `memory.current` sampling;
- least-squares RSS slope in MiB/hour after configurable warmup;
- separate RSS growth and peak gates;
- repeated steady long-lived streams;
- high lifecycle churn from many short streams;
- repeated cancel/reconnect batches with exact expected/observed accounting;
- hard backend restart while RPCs are active;
- backend disruption is only valid when at least one in-flight RPC is actually interrupted;
- healthy RPC must recover after backend restart;
- deterministic raw HTTP/2 transport resets on a separate TLS listener of the same NGINX worker;
- exact expected/observed reset accounting and healthy recovery probe;
- final healthy probe after the complete soak;
- NGINX master PID and Docker `RestartCount` must remain unchanged;
- strict soak inherits M12 host preflight and CPU isolation;
- default strict policy requires at least two hours; an eight-hour release-candidate soak is recommended;
- shared CI performs a bounded orchestration smoke only and remains `harness_only/inconclusive`.

**Exit:** pure trend/lifecycle tests green; TLS/H2 soak smoke proves steady/churn/cancel/backend-crash/reset/recovery mechanics on one worker; exact standard CI matrix remains green; production module C behavior is unchanged. A real production-readiness claim additionally requires preserved strict controlled 2-hour and release-candidate 8-hour artifacts on target-class hardware.

### M13 restart finding

The first soak smoke used ordinary `docker compose restart backend`. Docker's default graceful stop window allowed the short benchmark streams to finish before backend termination, so the test correctly rejected the run with `backend_disruption` even though recovery succeeded.

The perf backend now uses `stop_grace_period: 0s` specifically for the M13 topology. This turns restart into a deterministic hard disruption: active RPCs must fail, after which the same NGINX worker must recover on the next healthy request. The production backend/application behavior is not changed.

### M13 memory interpretation

A short before/after RSS delta is still useful for regression tests but is not sufficient for soak evidence. M13 excludes warmup and estimates memory trend over many samples. Shared CI uses intentionally broad memory limits only to validate the sampler/evaluator path; its short-run slope must not be interpreted as a production leak or stability measurement.

## PR discipline

Один milestone может состоять из нескольких PR. Каждый PR должен оставлять репозиторий в объяснимом состоянии и не включать необязательные refactoring.
