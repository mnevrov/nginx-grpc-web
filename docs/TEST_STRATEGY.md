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

не требует изменения React-клиента и не вводит небезопасные parser/lifecycle semantics.

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

### 2. Sanitizer and fuzz gates

Pure C path обязательно прогоняется под:

- ASAN;
- UBSAN.

CI также собирает libFuzzer targets для:

- incremental Base64 encoder/decoder;
- native gRPC frame parser.

Каждый target получает минимум `20 000` bounded iterations в обычном PR CI. Fuzz properties проверяют не конкретный chunking, а инварианты state machine: отсутствие OOB/UB, ограниченный internal state, отсутствие oversized output и round-trip для валидно закодированных произвольных bytes.

Длительный fuzzing может выполняться отдельно от PR gate; найденный crash обязательно превращается в минимальный deterministic regression corpus/test.

### 3. Reference tests

Envoy + deterministic backend.

Цель: зафиксировать baseline ожидаемого grpc-web поведения независимо от нашей реализации.

Envoy — semantic oracle, а не требование копировать внутреннюю реализацию или TCP/Base64 packetization.

### 4. Module integration tests

Те же requests через NGINX module, плюс NGINX-specific defensive cases:

- malformed requests;
- frame-size limits;
- worker/resource lifecycle;
- local gateway error normalization;
- raw upstream transport faults;
- logging leakage checks.

### 5. Differential tests

Одинаковый сценарий прогоняется через Envoy и NGINX там, где Envoy формирует сравнимый observable contract.

Сравнивать:

- decoded DATA frame sequence;
- payload bytes;
- metadata;
- trailer map;
- grpc status/message;
- terminal state;
- ordering/timing shape where relevant.

Не сравнивать как обязательный контракт:

- TCP packetization;
- HTTP chunk boundaries;
- границы Base64 output chunks;
- implementation-specific error text;
- synthetic terminal status, которого не создаёт сам Envoy.

### 6. Browser tests

Настоящий React test app использует стандартный `grpc-web` runtime.

Запрещены NGINX-specific branches/workarounds в клиенте. Endpoint и параметры сценария могут меняться только как test input.

Browsers:

- Chromium обязательно для M0–M7;
- Firefox и WebKit добавляются в M8 compatibility matrix.

### 7. Streaming timing tests

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

### 8. Raw transport fault injection

Отдельный HTTP/2 backend без gRPC framework нужен, потому что `context.abort()` создаёт валидный gRPC terminal status и не моделирует повреждение transport layer.

Fault backend должен уметь детерминированно воспроизводить:

- `RST_STREAM` до response headers;
- `RST_STREAM` после завершённого DATA frame;
- TCP reset после DATA;
- oversized native gRPC frame declaration;
- truncated native frame;
- HTTP/2 EOF после DATA без обязательных native gRPC trailers.

#### Oracle rule для reset после DATA

Не требовать terminal `grpc-status` parity автоматически.

Наблюдение M7: Envoy после завершённого DATA + raw upstream `RST_STREAM` сохраняет DATA для браузера, но может не вызвать terminal `error/status/end`; RPC остаётся `running`.

Поэтому критерии разделены:

- reset **до** DATA/headers: React-visible terminal error NGINX должен соответствовать Envoy;
- reset **после** завершённого DATA: DATA должен сохраниться byte-exact, lifecycle/memory должен остаться bounded, следующий normal request должен быть здоров;
- отсутствие native gRPC trailers никогда не должно превращаться в ложный `grpc-status: 0`.

Такой oracle не навязывает NGINX поведение, более сильное, чем reference implementation.

## Обязательная матрица сценариев

| Scenario | Envoy | NGINX | Browser / gate |
|---|---:|---:|---|
| unary text success | ✅ | ✅ | Chromium ✅ |
| unary binary success | ✅ | ✅ | Chromium ✅ |
| server stream 3 events | ✅ | ✅ | Chromium ✅ |
| 100 small events | ✅ | ✅ | protocol |
| empty stream | ✅ | ✅ | Chromium ✅ |
| large allowed message | ✅ | ✅ | protocol |
| custom request metadata | ✅ | ✅ | protocol |
| response metadata | ✅ | ✅ | protocol |
| custom trailers | ✅ | ✅ | protocol |
| grpc-status non-zero | ✅ | ✅ | Chromium ✅ |
| grpc-message | ✅ | ✅ | Chromium ✅ |
| trailers-only | ✅ | ✅ | protocol/browser |
| client cancel | ✅ | ✅ | Chromium + upstream propagation |
| backend unavailable | ✅ | ✅ | matching gRPC status |
| proxy timeout | ✅ | ✅ | matching gRPC status |
| `RST_STREAM` before headers | ✅ | ✅ | Chromium terminal parity |
| `RST_STREAM` after DATA | reference observed | ✅ | DATA preservation + lifecycle; terminal parity n/a |
| TCP reset after DATA | fault reference | ✅ | DATA preservation + lifecycle |
| malformed base64 | baseline | ✅ reject | protocol |
| partial base64 quartet | baseline | ✅ reject | unit/protocol |
| fragmented frame header | baseline | ✅ | unit/protocol |
| unsupported `+json`/lookalike media type | n/a | ✅ inactive | protocol |
| supported media type + parameters | n/a | ✅ | protocol |
| oversized native frame | defined fault | ✅ reject before amplification | RSS `<16 MiB` |
| truncated native frame | defined fault | ✅ no poisoned worker | healthy next request |
| DATA + EOF without native trailers | defined fault | ✅ no false success | no `grpc-status: 0` |
| repeated after-DATA resets | n/a | ✅ | RSS `<16 MiB` + healthy next request |
| repeated downstream disconnects | n/a | ✅ | RSS `<16 MiB` + healthy next request |
| malformed request with secret metadata/payload | n/a | ✅ | secret absent from NGINX logs |

## Memory and lifecycle gates

Memory tests compare NGINX worker RSS before/after a deterministic stress scenario rather than relying only on process survival.

Current regression gates:

- long valid stream: peak RSS delta `<32 MiB` for the M5 stress case;
- repeated oversized-frame attacks: RSS delta `<16 MiB`;
- repeated raw after-DATA transport faults: RSS delta `<16 MiB`;
- repeated downstream disconnect/cancellation: RSS delta `<16 MiB`.

После каждого destructive/fault scenario выполняется нормальный gRPC-Web request. Это проверяет, что worker/request state не только не упал, но и не остался логически повреждённым.

## Logging security

Error/info logging должно помогать диагностике без утечки application content.

Regression обязан передать уникальный secret одновременно в malformed request payload и `Authorization`, вызвать error path и затем подтвердить, что этот secret отсутствует в NGINX logs.

Запрещено добавлять production logs с:

- request/response protobuf payload;
- authorization tokens;
- arbitrary metadata values;
- raw Base64 body fragments.

## CI gating

После M7 обязательный PR gate включает:

1. unit tests;
2. ASAN/UBSAN;
3. bounded libFuzzer smoke;
4. dynamic module build на поддерживаемых NGINX versions;
5. Envoy reference;
6. NGINX integration/hardening;
7. Envoy ↔ NGINX differential;
8. real React/`grpc-web` Chromium tests.

Нельзя оставлять `xfail`/skip без ссылки на milestone/issue. После реализации конкретного behavior соответствующий skip удаляется в том же PR.
