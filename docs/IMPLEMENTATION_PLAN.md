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

## M8 — Compatibility & rollout

- current NGINX stable + mainline compatibility matrix;
- GCC + Clang module builds;
- Chromium + Firefox + WebKit browser matrix where supported by `grpc-web`/Playwright;
- installation and packaging instructions for the dynamic module;
- production NGINX configuration examples;
- observability and operational guidance;
- safe Envoy -> NGINX rollout/canary/rollback guide;
- final release checklist and versioned artifact guidance.

**Exit:** supported build/runtime matrix documented and green; operators have a reproducible installation, migration, verification and rollback procedure for v0.1.

## PR discipline

Один milestone может состоять из нескольких PR. Каждый PR должен оставлять репозиторий в объяснимом состоянии и не включать необязательные refactoring.
