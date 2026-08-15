# nginx-grpc-web

Нативный dynamic module для NGINX, реализующий **только** адаптацию протокола gRPC-Web ↔ native gRPC.

Цель проекта — убрать отдельный Envoy из тракта React → backend без изменения React-клиента и без дублирования возможностей NGINX.

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

Envoy используется в тестовом стенде как **reference oracle**, а не как production-зависимость.

## Жёсткие границы scope

Модуль отвечает за:

- распознавание gRPC-Web media types;
- преобразование request headers;
- incremental Base64 decode для `grpc-web-text`;
- passthrough binary gRPC-Web request body;
- преобразование response headers;
- incremental response transformation;
- преобразование native gRPC trailers в gRPC-Web trailer frame;
- корректную передачу `grpc-status`, `grpc-message`, metadata;
- server streaming без буферизации всего ответа;
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

## Ключевой критерий готовности

> Существующий React-клиент на `grpc-web` должен переключаться с Envoy на NGINX только изменением маршрута/endpoint. Изменения клиентского кода запрещены.

## Поддерживаемая первая версия

| Возможность | v0.1 |
|---|---|
| `application/grpc-web+proto` unary | ✅ |
| `application/grpc-web-text+proto` unary | ✅ |
| `application/grpc-web-text+proto` server streaming | ✅ |
| Native gRPC backend | ✅ |
| gRPC trailers/status | ✅ |
| Client cancellation | ✅ |
| Deadline / `grpc-timeout` | ✅ |
| Local upstream unavailable / timeout normalization | ✅ |
| CORS | вне scope |
| client streaming | вне scope |
| bidi streaming | вне scope |
| grpc-web JSON | вне scope |

Поддерживаемые media-type tokens распознаются строго: `application/grpc-web`, `application/grpc-web+proto`, `application/grpc-web-text`, `application/grpc-web-text+proto`. Параметры после `;` допустимы; `+json`, произвольные suffixes и prefix-lookalikes не активируют модуль.

## Быстрый старт

Требования:

- Docker + Docker Compose;
- Python 3.11+ для protocol tests;
- Node.js 22+ для browser/fault tests;
- GCC/Clang для разработки C-модуля.

```bash
make reference-up
make test-reference
```

Для реализованных M2–M7 путей:

```bash
# backend + NGINX module
make module-up

# unary/streaming/failure/hardening integration
make test-module

# canonical Envoy ↔ NGINX comparison
make reference-up
make test-diff

# real React/grpc-web client in Chromium
make test-browser

# pure C parser/state-machine hardening
make sanitizers CC=clang
make fuzz-smoke FUZZ_CC=clang
```

## Репозиторий устроен как test-first проект

```text
src/                  NGINX module
tests/backend/        deterministic native gRPC backend
tests/fault_backend/  raw HTTP/2 transport-fault injector
tests/protocol/       protocol/differential/hardening tests
tests/fuzz/           libFuzzer targets
tests/browser/        real React + grpc-web + Playwright harness
docker/envoy/         reference gateway
docker/nginx/         NGINX with dynamic module
docs/                 protocol/architecture/DoD
prompts/              prompts for coding agents
AGENTS.md              обязательные правила для агентов
```

Перед любыми изменениями агент обязан прочитать:

1. `AGENTS.md`
2. `docs/PROTOCOL_CONTRACT.md`
3. `docs/TEST_STRATEGY.md`
4. `docs/DEFINITION_OF_DONE.md`

## Принцип oracle

Envoy считается reference implementation для наблюдаемого поведения, но тесты не требуют бессмысленного byte-for-byte совпадения Base64 chunk boundaries.

Сравнивается **каноническая семантика**:

- sequence decoded gRPC DATA frames;
- payload bytes;
- metadata;
- trailers;
- `grpc-status`;
- `grpc-message`;
- порядок событий;
- отсутствие искусственной буферизации stream;
- cancellation/error semantics;
- React-visible status для gateway failures, когда Envoy сам формирует terminal semantics.

Для raw transport fault после уже доставленного DATA Envoy не всегда синтезирует terminal grpc-web status. В таком случае oracle — не выдуманный status parity, а сохранность уже завершённых DATA frames, bounded lifecycle и работоспособность следующего запроса.

## Текущее состояние

### M0–M1 — oracle и module skeleton ✅

Собраны воспроизводимый Envoy reference harness и динамический NGINX module с `grpc_web on|off`.

### M2 — binary unary ✅

- gRPC-Web binary request headers нормализуются для native `ngx_http_grpc_module`;
- binary request/response DATA framing проходит без protobuf parsing;
- native gRPC trailers преобразуются в terminal gRPC-Web trailer frame;
- NGINX и Envoy сравниваются canonical differential test;
- тот же React `grpc-web` binary client проверяется через Playwright против обоих gateway.

### M3 — grpc-web-text request ✅

- Base64 декодируется statefully между произвольными request-body buffers;
- fixed `Content-Length` и chunked downstream requests поддерживаются отдельно;
- encoded downstream `Content-Length` не уходит в native gRPC upstream как decoded length;
- malformed/incomplete Base64 отклоняется с `400`;
- fragmentation и request semantics сверяются с Envoy.

### M4 — grpc-web-text response ✅

- response text mode выбирается по `Accept: application/grpc-web-text[+proto]`;
- native gRPC frame может пересекать произвольное число NGINX upstream buffers;
- модуль буферизует только текущий gRPC frame, а не весь HTTP response;
- каждый завершённый native gRPC frame Base64-кодируется отдельно;
- native trailers преобразуются в `0x80 | uint32 length | CRLF trailer block`;
- `grpc-status`, `grpc-message` и trailing metadata сохраняются;
- trailers-only `HEADERS+END_STREAM` поддерживается отдельно.

### M5 — server streaming и bounded memory ✅

- первое React `data` event наблюдается до завершения RPC;
- backend inter-message delays сохраняются на downstream;
- большие DATA frames проходят при `grpc_buffer_size 1k` и пересекают несколько upstream buffers;
- final trailers после нескольких DATA frames сохраняются;
- slow-consumer regression проверяет backpressure;
- long-stream RSS regression проверяет bounded memory lifecycle.

Первоначальный M5 stress на 480 сообщений примерно по 64 KiB выявил удержание per-frame allocations в `r->pool`: при ~40 MiB gRPC-Web text output RSS вырос на **70.2 MiB**. После перехода на reusable native-frame scratch buffer и NGINX `free`/`busy` chains тот же тест проходит с gate `<32 MiB`.

### M6 — cancellation and failures ✅

M6 доказал корректность application-level failure semantics через stock `ngx_http_grpc_module`:

- clean empty server stream;
- non-zero gRPC status после одного или нескольких DATA frames;
- `grpc-timeout` / `DEADLINE_EXCEEDED`;
- downstream client disconnect / browser `cancel()` с закрытием upstream RPC.

Для локальных proxy errors добавлена узкая нормализация **только для уже распознанных grpc-web requests**:

| Local HTTP status | Terminal gRPC status | Message |
|---|---:|---|
| `502`, `503` | `14 UNAVAILABLE` | `upstream unavailable` |
| `504`, `408` | `4 DEADLINE_EXCEEDED` | `upstream timeout` |

Стандартный NGINX HTML error body при этом отбрасывается и заменяется корректным terminal gRPC-Web trailer frame.

### M7 — hardening ✅

M7 добавляет отдельные defensive gates вокруг production path, не превращая модуль в собственный HTTP/2 transport.

**Parser/state-machine hardening:**

- C unit tests запускаются под ASAN + UBSAN;
- incremental Base64 encoder/decoder и native gRPC frame parser имеют libFuzzer targets;
- CI выполняет по 20 000 bounded fuzz iterations на каждый target;
- malformed/incomplete Base64 и arbitrary fragmentation остаются regression-gated.

**Media type boundary:**

Первый M7 test-first прогон обнаружил реальный bug: prefix matcher ошибочно активировал модуль для `+json`, `+protoevil` и других похожих Content-Type. Production fix заменил prefix matching на точное сравнение четырёх поддерживаемых media-type tokens с разрешёнными параметрами после `;`.

**Raw transport fault injection:**

Тестовый HTTP/2 backend без gRPC framework умеет детерминированно выдавать:

- `RST_STREAM` до response headers;
- `RST_STREAM` после завершённого DATA frame;
- TCP reset после DATA;
- oversized native frame declaration;
- truncated native frame;
- clean HTTP/2 EOF после DATA без обязательных native gRPC trailers.

`RST_STREAM` до DATA сравнивается через настоящий React/`grpc-web` client с Envoy. Для reset после DATA обнаружено важное поведение reference implementation: Envoy сохраняет уже доставленный DATA, но может не выдавать browser terminal `error/status/end`. Поэтому NGINX здесь не обязан синтезировать более сильную семантику, чем oracle; вместо этого тесты требуют byte-exact сохранения завершённого DATA, bounded memory/lifecycle и здорового следующего request.

**Resource/lifecycle hardening:**

- 25 oversized-frame атак при `grpc_web_max_frame_size 1k` должны быть отвергнуты до memory amplification; RSS gate `<16 MiB`;
- repeated truncated-frame faults не должны отравлять worker state;
- raw RST/TCP-reset после DATA повторяются сериями с RSS gate `<16 MiB`;
- 30 downstream disconnects активных streams проходят с RSS gate `<16 MiB`;
- DATA без native trailers никогда не превращается в ложный `grpc-status: 0`;
- malformed request с уникальным secret в payload и `Authorization` проверяет отсутствие этого secret в NGINX logs.

### Последняя M7 функциональная валидация

Полный CI M7 прошёл:

- unit tests — ✅;
- ASAN/UBSAN — ✅;
- libFuzzer Base64 — `20 000` runs ✅;
- libFuzzer frame parser — `20 000` runs ✅;
- dynamic module build на NGINX 1.30.2 — ✅;
- dynamic module build на NGINX 1.31.1 — ✅;
- Envoy reference — `2 passed`;
- NGINX module integration — `43 passed`;
- Envoy ↔ NGINX differential — `8 passed`;
- React/`grpc-web`/Chromium — `19 passed`.

Следующий milestone — **M8: compatibility & rollout**: актуальная stable/mainline NGINX matrix, GCC/Clang build matrix, расширенная browser matrix, installation/packaging, deployment examples и безопасный Envoy → NGINX rollout guide.
