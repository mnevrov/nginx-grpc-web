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

Таблица выше описывает целевой scope `v0.1`; hardening и compatibility matrix продолжаются в M7/M8.

## Быстрый старт

Требования:

- Docker + Docker Compose;
- Python 3.11+ для локальных protocol tests;
- Node.js 22+ для browser tests;
- GCC/Clang для разработки C-модуля.

```bash
make reference-up
make test-reference
```

Для реализованных M2–M6 путей:

```bash
# backend + NGINX module
make module-up

# unary/streaming/failure integration,
# включая backpressure, RSS, cancellation и local gateway errors
make test-module

# canonical Envoy ↔ NGINX comparison
make reference-up
make test-diff

# real React/grpc-web client in Chromium
make test-browser
```

## Репозиторий устроен как test-first проект

```text
src/                  NGINX module
tests/backend/        deterministic native gRPC backend
tests/protocol/       protocol/differential tests
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

- sequence decoded gRPC data frames;
- payload bytes;
- metadata;
- trailers;
- `grpc-status`;
- `grpc-message`;
- порядок событий;
- отсутствие искусственной буферизации stream;
- cancellation/error semantics;
- React-visible status для gateway failures.

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

M6 сначала доказал, что application-level failure semantics уже корректно наследуются от stock `ngx_http_grpc_module` без изменения production path:

- clean empty server stream;
- non-zero gRPC status после одного или нескольких DATA frames;
- `grpc-timeout` / `DEADLINE_EXCEEDED`;
- downstream client disconnect / browser `cancel()` с закрытием upstream RPC.

Отдельный browser oracle выявил реальный gap только для локальных proxy errors. До M6 NGINX возвращал обычные HTML `502/504`, и `grpc-web` интерпретировал их как `UNKNOWN (2)`, тогда как Envoy давал семантически полезный terminal gRPC status.

M6 добавляет узкую нормализацию **только для уже распознанных grpc-web requests**:

| Local HTTP status | Terminal gRPC status | Message |
|---|---:|---|
| `502`, `503` | `14 UNAVAILABLE` | `upstream unavailable` |
| `504`, `408` | `4 DEADLINE_EXCEEDED` | `upstream timeout` |

Для этих случаев модуль:

1. заменяет downstream HTTP status на `200`;
2. выставляет соответствующий gRPC-Web media type;
3. отбрасывает стандартный NGINX HTML error body;
4. формирует единственный terminal trailer frame `0x80 | length | grpc-status/grpc-message`;
5. в text mode Base64-кодирует этот frame существующим bounded output path.

Raw protocol regressions требуют именно корректный gRPC-Web wire response, а Playwright проверяет итоговый code через настоящий `grpc-web` client. Application mid-stream failure дополнительно проверяется на сохранение уже полученных DATA перед terminal status.

**Граница M6:** сценарий `context.abort()` после DATA покрывает корректный gRPC terminal status, но не имитирует сырой HTTP/2 `RST_STREAM` или TCP reset после начала response. Такой transport-level fault injection вынесен в M7 hardening.

### Последняя M6 валидация

Functional head `d99dc8fe02991c1826b7ad68d4c22fe427c34987` прошёл полный CI:

- unit tests — ✅;
- dynamic module build на NGINX 1.30.2 — ✅;
- dynamic module build на NGINX 1.31.1 — ✅;
- Envoy reference — `2 passed`;
- NGINX module integration — `23 passed`;
- Envoy ↔ NGINX differential — `8 passed`;
- React/`grpc-web`/Chromium — `18 passed`.

Следующий milestone — **M7: hardening**: sanitizers, malformed/fuzz corpus, transport-level reset fault injection, overflow/size-limit review, leak/lifecycle checks и logging review.
