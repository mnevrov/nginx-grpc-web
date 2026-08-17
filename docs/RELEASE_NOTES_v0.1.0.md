# nginx-grpc-web v0.1.0

Дата подготовки: 2026-08-15.

## Что это за релиз

`v0.1.0` — первый production-oriented релиз проекта `ngx_http_grpc_web_module`, предназначенного для удаления Envoy grpc_web filter из request path без изменения существующего React/`grpc-web` клиента.

Целевая схема:

```text
React/browser -> gRPC-Web -> NGINX + ngx_http_grpc_web_module -> native gRPC -> backend
```

Модуль выполняет только protocol adaptation gRPC-Web ↔ native gRPC. HTTP/2 upstream transport, routing, load balancing и connection management остаются в штатном `ngx_http_grpc_module`.

## Поддерживаемый protocol scope

- binary gRPC-Web;
- text/base64 gRPC-Web;
- `+proto` media types;
- unary RPC;
- server-side streaming;
- metadata/trailers/status;
- cancellation/deadline;
- локальные proxy failures с gRPC-Web terminal semantics.

Не входят в scope:

- client streaming;
- bidi streaming;
- JSON;
- CORS/auth/router/service discovery/retries.

## Совместимость

Проверяемая CI-матрица релиза:

- NGINX stable `1.30.4`;
- NGINX mainline `1.31.3`;
- GCC и Clang dynamic-module build/load;
- Chromium;
- Firefox;
- WebKit;
- ASAN/UBSAN;
- Base64/frame libFuzzer smoke.

Binary `.so` должен собираться или проверяться для конкретного production NGINX package. Не следует распространять один generic module binary с обещанием ABI-совместимости со всеми дистрибутивными сборками.

## Основные гарантии v0.1.0

- существующий React grpc-web client не требует NGINX-specific изменений;
- protobuf payload остаётся opaque;
- response не буферизуется целиком;
- server stream выдаётся браузеру инкрементально;
- Base64 block boundaries не привязаны к HTTP chunks;
- normal native trailers кодируются в gRPC-Web trailer frame;
- trailers-only gRPC response сохраняет валидную browser semantics;
- malformed/incomplete upstream не может стать ложным `grpc-status: 0`;
- bounded frame/output buffer lifecycle проверяется RSS stress tests;
- `Authorization` и payload secrets не должны логироваться модулем.

## Validation evidence

M8 PR exact green head:

```text
40561a509081a0c57566d254a9810842f2f96008
```

M8 GitHub Actions:

```text
run #75
id: 31884895618
result: success
```

M8 merge commit в `main`:

```text
82729f5f3e026df820b01cfb5a9d2d36a7f31d85
```

Post-merge `main` CI:

```text
run #76
id: 31888310660
result: success
commit: 82729f5f3e026df820b01cfb5a9d2d36a7f31d85
```

Это подтверждённая code baseline для `v0.1.0`. Release-prep PR добавляет только changelog/release metadata. После его merge тег `v0.1.0` должен указывать на resulting `main` commit **только после** зелёного post-merge CI этого commit.

M14/M15 (PR #17, PR #21) merge commit и post-merge CI:

```text
release_commit: c22867c0d643dea069dd1bc605540dfe5f1c17be
post-merge ci run: 32039399834
result: success
```

## Validation status

Completed before v0.1.0:

- protocol/unit/integration CI;
- NGINX compatibility matrix (1.30.4 / 1.31.3, GCC / Clang);
- browser grpc-web regression tests (Chromium/Firefox/WebKit);
- sanitizers/hardening (ASAN/UBSAN, Base64/frame fuzz smoke);
- packaging and release-evidence mechanics (M14);
- M15 benchmark/soak/staging tooling validation (unit/contract tests, CI mechanics).

Deferred post-release validation:

- dedicated-host capacity benchmark;
- five-repeat controlled performance campaign;
- 2-hour strict soak;
- recommended 8-hour soak;
- real staging deployment;
- production-like React acceptance;
- Envoy rollback exercise.

The deferred tests do not change the v0.1 protocol scope. Their results will be tracked separately in [Issue #20](https://github.com/mnevrov/nginx-grpc-web/issues/20) and in `docs/POST_RELEASE_VALIDATION_v0.1.0.md`.

Any prior CI/shared-runner numeric observations remain `harness_only` / non-production measurements and are not promoted to `controlled` evidence. This release does not claim production-proven capacity, a specific performance delta versus Envoy, or a specific stream-concurrency figure — those claims require the deferred controlled-host evidence above.

## Artifact

Рекомендуемый baseline artifact:

```text
ngx_http_grpc_web_module-v0.1.0-nginx-1.30.4-linux-amd64-gcc.so
```

Сборка:

```bash
make package-module NGINX_VERSION=1.30.4 BUILD_CC=gcc
```

Публиковать вместе с:

- `MANIFEST.txt`;
- `SHA256SUMS`;
- exact project tag/commit;
- exact NGINX version;
- compiler;
- architecture/build environment;
- ABI compatibility disclaimer.

## Rollout

Рекомендуемый production rollout остаётся canary-based:

```text
baseline -> 1% -> 5-10% -> 25-50% -> 100%
```

Envoy rollback pool сохраняется на согласованное observation window. Удаление Envoy как инфраструктурного компонента выполняется отдельным change после стабильного наблюдения на 100% NGINX path.

См. `docs/DEPLOYMENT.md`, `docs/ROLLOUT.md` и `docs/RELEASE_CHECKLIST.md`.
