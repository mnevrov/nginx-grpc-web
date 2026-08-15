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

## M6 — Cancellation and failures

- browser cancel;
- backend reset;
- backend unavailable;
- upstream timeout/deadline;
- trailers-only;
- empty stream;
- mid-stream failure after one or more DATA frames.

**Exit:** failure matrix green and observable React behavior matches Envoy semantics where applicable.

## M7 — Hardening

- size limits;
- overflow guards;
- malformed fuzz corpus;
- ASAN/UBSAN;
- leak checks;
- logging review.

## M8 — Compatibility

- NGINX stable + mainline;
- GCC + Clang;
- browser matrix;
- documentation;
- rollout guide.

## PR discipline

Один milestone может состоять из нескольких PR. Каждый PR должен оставлять репозиторий в объяснимом состоянии и не включать необязательные refactoring.
