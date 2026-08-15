# nginx-grpc-web

Нативный dynamic module для NGINX, реализующий **только** адаптацию протокола gRPC-Web ↔ native gRPC.

Цель проекта — убрать отдельный Envoy из production-тракта React → backend без изменения React-клиента и без дублирования возможностей NGINX.

## Целевая архитектура

```text
React / grpc-web
      |
      | application/grpc-web[-text][+proto]
      v
NGINX
  ├─ ngx_http_grpc_web_module   ← этот проект
  └─ ngx_http_grpc_module       ← штатный transport до backend
      |
      | HTTP/2 + application/grpc
      v
gRPC services
```

Envoy остаётся в тестовом стенде как **reference oracle**, а не как production-зависимость.

## Жёсткие границы scope

Модуль отвечает за:

- распознавание gRPC-Web media types;
- преобразование request headers;
- incremental Base64 decode для `grpc-web-text`;
- passthrough binary gRPC-Web request body;
- преобразование response headers;
- incremental response transformation;
- native gRPC trailers → gRPC-Web trailer frame;
- сохранение `grpc-status`, `grpc-message`, metadata;
- server streaming без буферизации всего ответа;
- cancellation/deadline semantics;
- нормализацию выбранных локальных NGINX gateway errors в terminal gRPC-Web status.

Модуль **не** отвечает за:

- CORS;
- auth;
- routing;
- TLS termination;
- load balancing;
- retries/circuit breakers;
- service discovery;
- protobuf parsing;
- REST/JSON transcoding;
- WebSocket/SSE.

Эти задачи остаются NGINX/инфраструктуре.

## Главный compatibility criterion

> Существующий React-клиент на `grpc-web` должен переключаться с Envoy на NGINX только изменением маршрута/endpoint. NGINX-specific frontend workaround считается ошибкой реализации.

## Поддерживаемая v0.1

| Возможность | v0.1 |
|---|---|
| `application/grpc-web+proto` unary | ✅ |
| `application/grpc-web-text+proto` unary | ✅ |
| `application/grpc-web-text+proto` server streaming | ✅ |
| Native gRPC backend | ✅ |
| gRPC trailers/status/metadata | ✅ |
| Client cancellation | ✅ |
| Deadline / `grpc-timeout` | ✅ |
| Local upstream unavailable / timeout normalization | ✅ |
| CORS | вне scope |
| client streaming | вне scope |
| bidi streaming | вне scope |
| grpc-web JSON | вне scope |

Поддерживаемые media-type tokens распознаются строго:

- `application/grpc-web`;
- `application/grpc-web+proto`;
- `application/grpc-web-text`;
- `application/grpc-web-text+proto`.

Параметры после `;` допустимы. `+json`, произвольные suffixes и prefix-lookalikes модуль не активируют.

## Compatibility matrix

Актуальная M8-матрица на 2026-08-15:

| Слой | Проверяемые targets |
|---|---|
| NGINX stable | `1.30.4` |
| NGINX mainline | `1.31.3` |
| compiler | GCC, Clang |
| browser engine | Chromium, Firefox, WebKit |

Stable/mainline проходят отдельный protocol/hardening/differential runtime suite. Каждый NGINX target дополнительно собирает и **реально загружает** dynamic module через `nginx -t` с GCC и Clang.

Browser matrix использует настоящий React + официальный `grpc-web` runtime против stable NGINX и Envoy oracle.

Предыдущие CI targets `1.30.2 / 1.31.1` больше не являются production-рекомендацией: последующие NGINX security releases содержат исправление, затрагивающее `ngx_http_grpc_module`.

Подробный contract: [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md).

## Быстрый старт разработки

Требования:

- Docker + Docker Compose;
- Python 3.11+;
- Node.js 22+;
- Go 1.23+ для perf loadgen;
- OpenSSL для TLS/H2 perf profile;
- GCC/Clang.

Envoy oracle:

```bash
make reference-up
make test-reference
```

NGINX module:

```bash
make module-up
make test-module
make test-diff
```

Browser tests:

```bash
cd tests/browser
npm install
npx playwright install chromium firefox webkit
cd ../..

# вся browser matrix
make test-browser

# один engine
make test-browser BROWSER=firefox
```

Hardening:

```bash
make sanitizers CC=clang
make fuzz-smoke FUZZ_CC=clang
```

Performance A/B:

```bash
# controlled cleartext HTTP/1.1 baseline
make perf-smoke
make perf-typical
make perf-large
make perf-slow

# production-like TLS + HTTP/2 frontend
make perf-h2-smoke
make perf-h2-typical
make perf-h2-large
make perf-h2-slow

# SLO-driven sustainable-capacity staircase
PERF_CAPACITY_SLO=/data/slo.json make perf-capacity
PERF_CAPACITY_SLO=/data/slo.json make perf-h2-capacity
```

Perf suite сравнивает:

```text
legacy: loadgen -> NGINX -> Envoy -> backend
native: loadgen -> NGINX(module) -> backend
```

`perf-h2-*` строго требует валидный TLS chain, HTTP/2 и ALPN `h2`; silent fallback на HTTP/1.1 считается ошибкой. Large profile проверяет 1/4/8 MiB DATA, text/binary и concurrency 1/4/16. CPU/RSS снимаются host-side через cgroup v2.

M11 capacity mode выполняет A/B/B/A на каждой ступени concurrency и классифицирует обе архитектуры по заданному SLO. Capacity — последняя непрерывно проходящая ступень от минимальной нагрузки; случайный pass после первого failed level не повышает результат.

M12 добавляет повторные controlled-host capacity runs и итоговый architecture decision. Strict run требует отдельные непересекающиеся CPU sets для gateway/backend/loadgen и одного host fingerprint во всех repeats. Shared CI всегда остаётся `harness_only` и не может породить production performance claim.

Пример controlled decision run:

```bash
PERF_FRONTEND=tls-h2 \
PERF_GATEWAY_CPUSET=2-5 \
PERF_BACKEND_CPUSET=6-7 \
PERF_LOADGEN_CPUSET=8-9 \
PERF_CAPACITY_SLO=/data/slo.json \
PERF_CONTROLLED_REPEATS=5 \
bash ./perf/run-controlled.sh
```

M13 проверяет долговременную устойчивость server streaming: steady/churn/cancel, hard backend restart, upstream transport resets, recovery и RSS trend одного NGINX worker.

```bash
# короткий harness smoke; не production evidence
make perf-soak-smoke

# strict controlled soak; default policy >= 2 hours
PERF_GATEWAY_CPUSET=2-5 \
PERF_BACKEND_CPUSET=6-7 \
PERF_LOADGEN_CPUSET=8-9 \
SOAK_OUTPUT_DIR=/data/bench/soak-2h \
make perf-soak
```

Для release candidate рекомендуется отдельный 8-часовой soak (`SOAK_DURATION_SECONDS=28800`). Основной memory gate — RSS slope в MiB/hour после warmup, а не только before/after delta.

Подробности:

- [`perf/README.md`](perf/README.md)
- [`docs/CAPACITY_BENCHMARKS.md`](docs/CAPACITY_BENCHMARKS.md)
- [`docs/CONTROLLED_BENCHMARKS.md`](docs/CONTROLLED_BENCHMARKS.md)
- [`docs/SOAK_TESTING.md`](docs/SOAK_TESTING.md)

Важно: CI perf/capacity/soak smoke проверяет **измерительный контур**, а не доказывает performance advantage или долговременную memory stability. Для архитектурного решения нужны controlled-host repeats; для production-readiness — strict soak.

Другой NGINX target локально:

```bash
make module-up NGINX_VERSION=1.31.3 BUILD_CC=clang
```

## Packaging dynamic module

Для artifact, проверяемого против соответствующего официального `nginx:<version>` image:

```bash
make package-module NGINX_VERSION=1.30.4 BUILD_CC=gcc
```

Получится:

```text
dist/nginx-1.30.4-gcc-linux-<arch>/
  ngx_http_grpc_web_module.so
  SHA256SUMS
  MANIFEST.txt
```

**Не считать этот `.so` универсальным для произвольных distro/vendor NGINX packages.** Для существующей установки сначала проверяется `nginx -V`; при неясной ABI-совместимости модуль пересобирается на целевой платформе.

Инструкция: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Production configuration

Минимальная идея location:

```nginx
load_module modules/ngx_http_grpc_web_module.so;

location /example.v1.ExampleService/ {
    grpc_web on;
    grpc_web_max_frame_size 64m;

    grpc_read_timeout 1h;
    grpc_send_timeout 1h;

    grpc_pass grpc://grpc_backend;
}
```

Полный пример: [`examples/nginx-grpc-web.conf`](examples/nginx-grpc-web.conf).

CORS/auth/routing намеренно отсутствуют в module example и должны настраиваться обычными средствами NGINX/edge.

## Observability

На gateway уровне минимум нужны:

- HTTP `$status` и `$upstream_status`;
- request/upstream latency;
- 499/client disconnect rate;
- upstream reset/timeout/connect errors;
- worker RSS/CPU;
- active connections;
- bytes per stream;
- time-to-first-DATA для streaming.

Важно: application gRPC error обычно остаётся HTTP 200. Поэтому HTTP success rate **не заменяет** grpc-status telemetry. Для application SLI нужны backend/client/tracing metrics.

Не логировать request body или `Authorization` ради извлечения grpc-status. Hardening suite отдельно проверяет отсутствие таких secrets в module logs.

## Envoy → NGINX rollout

Рекомендуемый canary делается между двумя gateway pools:

```text
                         +-> legacy gateway -> Envoy -> backend
browser -> LB / ingress -|
                         +-> native gateway -> NGINX module -> backend
```

Это позволяет откатиться изменением веса трафика без frontend release и без срочного изменения protocol adapter.

Порядок: baseline → dark validation → 1% → 5–10% → 25–50% → 100%, сохраняя Envoy pool warm на согласованное rollback window.

До начала canary должны быть сохранены controlled performance/capacity artifacts M12 и strict soak artifacts M13 для exact release commit.

Полный runbook: [`docs/ROLLOUT.md`](docs/ROLLOUT.md).

Release checklist: [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md).

## Репозиторий

```text
src/                  NGINX module
tests/backend/        deterministic native gRPC backend
tests/fault_backend/  raw HTTP/2 transport-fault injector
tests/protocol/       protocol/differential/hardening tests
tests/fuzz/           libFuzzer targets
tests/browser/        real React + grpc-web + Playwright harness
perf/                 A/B loadgen, H1/H2, capacity, controlled decision, soak
docker/envoy/         reference gateway
docker/nginx/         NGINX module build/runtime image
examples/             production configuration examples
docs/                 protocol/architecture/testing/operations
prompts/              prompts for coding agents
AGENTS.md              обязательные правила для агентов
```

Перед изменениями implementation agent обязан прочитать:

1. `AGENTS.md`
2. `docs/PROTOCOL_CONTRACT.md`
3. `docs/TEST_STRATEGY.md`
4. `docs/DEFINITION_OF_DONE.md`
5. `docs/COMPATIBILITY.md`

## Принцип Envoy oracle

Envoy считается reference implementation для наблюдаемого поведения, но differential tests не требуют бессмысленного совпадения Base64 chunk boundaries, HTTP chunks или TCP packetization.

Сравнивается semantic contract:

- sequence decoded gRPC DATA frames;
- payload bytes;
- metadata/trailers;
- `grpc-status`/`grpc-message`;
- порядок browser events;
- отсутствие whole-stream buffering;
- cancellation/error semantics;
- first-DATA timing.

Для raw transport fault после уже доставленного DATA Envoy не всегда синтезирует terminal grpc-web status. В таком случае oracle — сохранность уже завершённых DATA frames, bounded lifecycle и работоспособность следующего request, а не выдуманный terminal parity.

## Milestones

### M0–M4 ✅

Построены Envoy oracle/harness и dynamic module skeleton; реализованы binary unary, incremental grpc-web-text request decode и frame-aware grpc-web-text response encode с trailer conversion.

### M5 — streaming/bounded memory ✅

Server streaming остаётся incremental. Stress testing обнаружил удержание per-frame allocations в request pool; reusable native-frame scratch buffer и NGINX `free/busy` output chains устранили рост памяти пропорционально длине stream.

### M6 — cancellation/failures ✅

Application gRPC aborts, deadlines и cancellation проходят через stock `ngx_http_grpc_module`. Local NGINX `502/503` адаптируются в `UNAVAILABLE (14)`, `504/408` — в `DEADLINE_EXCEEDED (4)` для уже распознанных grpc-web requests вместо HTML error body.

### M7 — hardening ✅

Добавлены exact media-type matching, ASAN/UBSAN, libFuzzer, raw HTTP/2 fault injection, oversized/truncated/missing-trailers regressions, repeated cancellation/reset RSS gates и secret logging test.

### M8 — compatibility & rollout ✅

- current stable/mainline NGINX matrix;
- GCC + Clang build/load matrix;
- Chromium + Firefox + WebKit browser matrix;
- versioned dynamic-module packaging;
- production config/install/observability docs;
- Envoy → NGINX canary/rollback runbook;
- v0.1 release checklist.

### M9 — streaming performance engine ✅

- Go grpc-web server-stream load generator;
- frame-aware text/binary decoding;
- backend-relative DATA timing;
- A/B/B/A legacy vs native topology;
- typical/large/slow profiles;
- cgroup v2 CPU, process RSS and cgroup-memory sampling;
- JSON + Markdown reports;
- CI topology smoke without treating shared-runner numbers as a performance result.

### M10 — TLS/HTTP2 benchmark path ✅

- production-like TLS + HTTP/2 listener on both gateway paths;
- ephemeral benchmark CA/certificate;
- strict CA + HTTP/2 + ALPN `h2` validation;
- protocol/TLS metadata in raw results;
- separate `perf-h2-*` profiles and CI gate;
- frontend dimension in reports so HTTP/1.1 and TLS/H2 samples cannot be mixed accidentally.

### M11 — capacity / SLO staircase ✅

- SLO-driven sustainable-capacity classifier;
- contiguous-pass rule and first-failure boundary;
- A/B/B/A at each concurrency level;
- HTTP/1 + TLS/H2 capacity targets;
- optional equal gateway CPU-set budget;
- machine-readable `capacity.json` + Markdown report;
- CI mechanics gates for both frontends;
- production capacity claims require controlled hardware and repeated full staircase runs.

### M12 — controlled benchmark decision ✅

- strict host fingerprint/preflight;
- isolated gateway/backend/loadgen CPU sets;
- repeated full capacity staircases;
- median/CV aggregation;
- same-load latency/CPU/RSS comparison;
- machine-readable `decision.json` + `decision.md`;
- shared CI forced to `harness_only/inconclusive`.

### M13 — soak / production readiness ✅

- continuous cgroup-v2 RSS trend and MiB/hour slope;
- steady, churn and exact client-cancellation accounting;
- hard backend restart during active streams + recovery;
- repeated raw HTTP/2 transport resets + recovery;
- final healthy probe;
- NGINX master PID / Docker RestartCount lifecycle gate;
- strict 2-hour baseline and recommended 8-hour release soak;
- shared CI only validates mechanics and remains `harness_only/inconclusive`.

Полная история и exit criteria: [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).
