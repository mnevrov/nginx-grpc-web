# Changelog

Все заметные изменения проекта фиксируются в этом файле.

## [0.1.0] — 2026-08-15

Первый production-oriented релиз NGINX dynamic module для преобразования gRPC-Web в native gRPC через штатный `ngx_http_grpc_module`.

### Added

- поддержка `application/grpc-web` и `application/grpc-web+proto`;
- поддержка `application/grpc-web-text` и `application/grpc-web-text+proto`;
- unary RPC и server-side streaming;
- stateful Base64 decode request body с произвольной NGINX fragmentation;
- frame-wise Base64 encode response без whole-stream buffering;
- native gRPC trailers → gRPC-Web trailer frame;
- корректная обработка trailers-only gRPC responses;
- client cancellation и deadline propagation;
- нормализация локальных NGINX `408/502/503/504` в gRPC-Web terminal status;
- bounded streaming memory через reusable scratch buffer и NGINX free/busy chains;
- hardening для malformed Base64, oversized/truncated frames, missing trailers и transport resets;
- ASAN/UBSAN и libFuzzer smoke targets;
- Envoy differential oracle;
- real React + `grpc-web` browser tests;
- compatibility matrix для NGINX 1.30.4 / 1.31.3, GCC / Clang, Chromium / Firefox / WebKit;
- versioned dynamic-module packaging с manifest и SHA256;
- production config, observability, canary/rollback и release checklist;
- M15 controlled-host RC benchmark / strict soak / staging-acceptance tooling and orchestration (mechanics validated by CI; controlled/soak/staging *evidence* deferred, see Validation status below and Issue #20).

### Scope

v0.1.0 намеренно не реализует:

- client streaming;
- bidirectional streaming;
- grpc-web JSON;
- CORS, auth, routing, retries или service discovery внутри модуля;
- собственный HTTP/2 upstream transport.

### Compatibility note

Готовый `.so` нельзя считать универсально ABI-совместимым со всеми vendor/distro NGINX packages. Binary artifact должен быть привязан к конкретной версии/сборке NGINX, compiler/toolchain, OS/architecture и сопровождаться SHA256.
