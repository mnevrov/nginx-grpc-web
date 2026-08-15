# Implementation Plan

Работа идёт маленькими проверяемыми этапами.

## M0 — Test oracle and harness

- deterministic gRPC backend;
- Envoy reference route;
- canonical gRPC-Web decoder in tests;
- React/grpc-web browser smoke;
- reference tests green.

**Exit:** Envoy path полностью воспроизводим локально и в CI.

## M1 — Module skeleton

- dynamic module builds for supported NGINX;
- `grpc_web on|off`;
- activation only for grpc-web content types;
- no behavior changes when off.

**Exit:** compile/config smoke green.

## M2 — Binary unary

- request header adaptation;
- binary body passthrough;
- response media type;
- native trailers -> grpc-web trailer frame.

**Exit:** binary unary differential + browser test green.

## M3 — Text unary request

- incremental base64 request decoder;
- arbitrary fragmentation;
- malformed input handling;
- content-length correctness.

**Exit:** text unary differential tests green.

## M4 — Text unary response

- incremental/semantic base64 output;
- trailer frame encode;
- non-zero status/message.

**Exit:** unary text browser tests green.

## M5 — Server streaming

- incremental response without whole-stream buffering;
- fragmented gRPC frames;
- slow backend;
- slow client/backpressure observation.

**Exit:** timing regression test green.

## M6 — Cancellation and failures

- browser cancel;
- backend reset;
- backend unavailable;
- trailers-only;
- empty stream.

**Exit:** failure matrix green.

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
