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
- incremental base64 decode для `grpc-web-text`;
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

Для уже реализованных M2/M3 путей:

```bash
# backend + NGINX module
make module-up

# binary unary + grpc-web-text request-side integration
make test-module

# canonical Envoy ↔ NGINX comparison
# (Envoy также должен быть запущен)
make reference-up
make test-diff

# browser regression: M2 binary path + Envoy text reference;
# NGINX text-mode browser path включается в M4
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

Envoy считается reference implementation для наблюдаемого поведения, но тесты не должны требовать бессмысленного byte-for-byte совпадения base64 chunk boundaries.

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

Полноценный `grpc-web-text` unary end-to-end пока **не считается реализованным**: M4 должен добавить response-side Base64 encoding и text trailer frame, после чего тот же React-клиент будет включён против NGINX text endpoint.
