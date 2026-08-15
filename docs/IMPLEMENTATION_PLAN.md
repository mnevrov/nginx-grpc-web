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

## M7 — Hardening

- raw HTTP/2 `RST_STREAM` / TCP reset fault injection before and after DATA;
- size-limit boundary tests for request, DATA frame and trailer block;
- integer overflow/underflow review and boundary corpus;
- malformed gRPC frame corpus;
- malformed/incomplete Base64 fuzz corpus;
- ASAN/UBSAN builds and tests;
- long-stream/leak/lifecycle checks beyond RSS smoke;
- cancellation/backpressure stress under repeated requests;
- logging review: useful diagnostics without request metadata/payload leakage;
- configuration misuse tests and safe failure behavior.

**Exit:** sanitizer/fuzz/fault-injection suite green and no known unbounded memory, parser-safety or transport-reset defects remain in supported scope.

## M8 — Compatibility

- NGINX stable + mainline;
- GCC + Clang;
- browser matrix;
- documentation;
- rollout guide.

## PR discipline

Один milestone может состоять из нескольких PR. Каждый PR должен оставлять репозиторий в объяснимом состоянии и не включать необязательные refactoring.
