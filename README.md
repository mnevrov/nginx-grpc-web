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
- server streaming без буферизации всего ответа.

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
| CORS | вне scope |
| client streaming | вне scope |
| bidi streaming | вне scope |

Таблица выше описывает целевой scope `v0.1`, а не текущую milestone-готовность. Актуальное состояние реализации приведено ниже.

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

Для реализованных M2–M4 путей:

```bash
# backend + NGINX module
make module-up

# binary unary + grpc-web-text request/response integration
make test-module

# canonical Envoy ↔ NGINX comparison
# (Envoy также должен быть запущен)
make reference-up
make test-diff

# real React/grpc-web client in Chromium:
# binary unary + text unary success/error against Envoy and NGINX
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

Envoy считается reference implementation для наблюдаемого поведения, но тесты не должны требовать бессмысленного byte-for-byte совпадения Base64 chunk boundaries.

Сравнивается **каноническая семантика**:

- sequence decoded gRPC data frames;
- payload bytes;
- metadata;
- trailers;
- `grpc-status`;
- `grpc-message`;
- порядок событий;
- отсутствие искусственной буферизации stream;
- cancellation/error semantics.

## Текущее состояние

M0/M1 завершены.

M2 реализует binary unary path:

- gRPC-Web binary request headers нормализуются для native `ngx_http_grpc_module`;
- binary request/response DATA framing проходит без protobuf parsing;
- native gRPC trailers преобразуются в terminal gRPC-Web trailer frame;
- NGINX и Envoy сравниваются canonical differential test;
- тот же React `grpc-web` binary client проверяется через Playwright против обоих gateway.

M3 реализует request-side `grpc-web-text`:

- Base64 декодируется statefully между произвольными request-body buffers;
- fixed `Content-Length` и chunked downstream requests поддерживаются отдельно;
- encoded downstream `Content-Length` не уходит в native gRPC upstream как decoded length;
- отдельный zero-length terminal callback передаётся как NGINX special control buffer, а не как пустой temporary data buffer;
- malformed/incomplete Base64 отклоняется с `400`;
- fragmentation и request semantics сверяются с Envoy.

M4 завершает `grpc-web-text` unary end-to-end:

- response text mode выбирается по `Accept: application/grpc-web-text[+proto]`, независимо от request `Content-Type`;
- native gRPC frame может пересекать произвольное число NGINX upstream buffers;
- модуль буферизует только текущий gRPC frame, а не весь HTTP response;
- каждый завершённый native gRPC frame Base64-кодируется отдельно;
- native trailers преобразуются в `0x80 | uint32 length | CRLF trailer block`, после чего Base64-кодируются отдельным terminal block;
- `grpc-status`, `grpc-message` и trailing metadata сохраняются;
- локальные HTTP-ошибки NGINX не пропускаются через native-gRPC response parser;
- upstream trailers-only `HEADERS+END_STREAM` поддерживается отдельно: stock `ngx_http_grpc_module` представляет такой status как обычные response headers, поэтому модуль сохраняет пустой body и только переписывает media type;
- большой unary response проверяется с `grpc_buffer_size 1k`, чтобы один native frame гарантированно пересекал несколько upstream buffers;
- успешный text unary и non-zero gRPC status/message проходят через тот же реальный React/`grpc-web` клиент против Envoy и NGINX.

### Последняя M4 валидация

Функциональный M4 head прошёл:

- unit tests — ✅;
- dynamic module build на NGINX 1.30.2 — ✅;
- dynamic module build на NGINX 1.31.1 — ✅;
- Envoy reference — `2 passed`;
- NGINX module integration — `13 passed`;
- Envoy ↔ NGINX differential — `4 passed`;
- React/`grpc-web`/Chromium — `7 passed`.

Следующий milestone — **M5: server streaming**. Его критерий готовности — первое сообщение должно доходить до браузера до завершения stream; полная буферизация ответа недопустима.