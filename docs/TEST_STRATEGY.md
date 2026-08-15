# Test Strategy

## Цель

Доказать, что замена:

```text
React -> NGINX -> Envoy -> gRPC
```

на:

```text
React -> NGINX(module) -> gRPC
```

не требует изменения React-клиента.

## Слои тестирования

### 1. Pure unit tests

Проверяют state machines без сети:

- incremental base64 decoder;
- incremental base64 encoder;
- 5-byte gRPC frame header parser;
- oversized frame rejection;
- trailer frame builder;
- arbitrary fragmentation.

Обязательный подход: property/table-driven fragmentation tests.

Для любого payload разбить input во всех разумных позициях:

```text
A|BCDE
AB|CDE
ABC|DE
ABCD|E
...
```

и получить тот же semantic output.

### 2. Reference tests

Envoy + deterministic backend.

Цель: зафиксировать baseline ожидаемого grpc-web поведения независимо от нашей реализации.

### 3. Module integration tests

Те же requests через NGINX module.

### 4. Differential tests

Одинаковый сценарий прогоняется через Envoy и NGINX.

Сравнивать:

- decoded DATA frame sequence;
- payload bytes;
- metadata;
- trailer map;
- grpc status/message;
- terminal state.

Не сравнивать как обязательный контракт:

- TCP packetization;
- HTTP chunk boundaries;
- границы base64 output chunks.

### 5. Browser tests

Настоящий React test app использует `grpc-web` runtime.

Запрещены NGINX-specific branches.

Browsers:

- Chromium обязательно;
- Firefox желательно;
- WebKit желательно.

### 6. Streaming timing tests

Backend:

```text
emit #1
sleep 250 ms
emit #2
sleep 250 ms
emit #3
```

Клиент должен увидеть события по мере поступления.

Тест должен иметь допуск для CI jitter, но обязан обнаруживать накопление всего stream до EOF.

## Обязательная матрица сценариев

| Scenario | Envoy | NGINX | Browser |
|---|---:|---:|---:|
| unary text success | ✅ | ✅ | ✅ |
| unary binary success | ✅ | ✅ | ✅ |
| server stream 3 events | ✅ | ✅ | ✅ |
| 100 small events | ✅ | ✅ | ✅ |
| empty stream | ✅ | ✅ | ✅ |
| zero-length protobuf message | ✅ | ✅ | ✅ |
| large allowed message | ✅ | ✅ | ✅ |
| custom request metadata | ✅ | ✅ | ✅ |
| response metadata | ✅ | ✅ | ✅ |
| custom trailers | ✅ | ✅ | ✅ |
| grpc-status non-zero | ✅ | ✅ | ✅ |
| grpc-message | ✅ | ✅ | ✅ |
| trailers-only | ✅ | ✅ | ✅ |
| client cancel | ✅ | ✅ | ✅ |
| backend unavailable | ✅ | ✅ | ✅ |
| backend reset mid-stream | ✅ | ✅ | ✅ |
| malformed base64 | ✅ | ✅ | n/a |
| partial base64 quartet | ✅ | ✅ | n/a |
| fragmented frame header | ✅ | ✅ | n/a |
| oversized frame | defined | ✅ reject | n/a |

## Sanitizers

Для C path:

- ASAN;
- UBSAN;
- Valgrind smoke where practical.

Fuzz target рекомендуется для:

- base64 decoder;
- frame parser;
- trailer parser/builder.

## CI gating

Bootstrap CI может держать ещё не реализованные module scenarios выключенными только по явному milestone marker.

Нельзя оставлять `xfail`/skip без ссылки на milestone/issue.

После реализации конкретного behavior соответствующий skip удаляется в том же PR.
