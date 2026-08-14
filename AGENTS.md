# AGENTS.md

Этот файл обязателен для всех coding agents.

## Миссия

Реализовать `ngx_http_grpc_web_module` как минимальный, безопасный и тестируемый адаптер gRPC-Web ↔ native gRPC для NGINX.

## Неподвижные инварианты

1. **React не меняется.** Нельзя добавлять client-side workaround ради NGINX.
2. **Только gRPC-Web.** Не добавлять CORS/auth/retries/router/service discovery.
3. **Не парсить protobuf.** Payload opaque.
4. **Не буферизовать весь server stream.**
5. **Не считать границы NGINX buffers границами base64 или gRPC frames.**
6. **Trailers обязательны.** `grpc-status` не должен потеряться.
7. **Envoy — oracle поведения**, но не byte-layout oracle для допустимо различающихся chunk boundaries.
8. Любой protocol behavior должен иметь тест.
9. Любое исправление race/fragmentation/error case должно начинаться с regression test.
10. Не патчить core NGINX без доказательства, что dynamic module API недостаточно.

## Разрешённый scope v0.1

- grpc-web binary unary;
- grpc-web-text unary;
- grpc-web-text server streaming;
- metadata passthrough;
- grpc status/message;
- trailers-only responses;
- cancellation;
- fragmented input/output;
- zero/large messages within configured limits.

Вне scope:

- client streaming;
- bidi streaming;
- JSON mode;
- gRPC transcoding;
- compression negotiation сверх прозрачного passthrough;
- CORS.

## Правила работы

Перед кодом:

1. прочитай `docs/PROTOCOL_CONTRACT.md`;
2. прочитай `docs/TEST_STRATEGY.md`;
3. найди аналогичное поведение в Envoy reference filter;
4. найди соответствующий lifecycle/hook в NGINX source;
5. сформулируй наблюдаемое поведение тестом;
6. только после этого меняй C-код.

## Запрещённые shortcuts

- `sleep` в production code;
- накопление всего response в memory;
- предположение, что `ngx_chain_t` содержит целый gRPC frame;
- преобразование base64 блоками без state между callbacks;
- игнорирование `last_buf`;
- преобразование любого HTTP ответа в успешный grpc-web;
- HTML error pages для gRPC-Web клиента;
- silent fallback при malformed input;
- изменение frontend API.

## Definition of Done для PR

PR считается готовым только если:

- scope описан;
- тест сначала воспроизводил проблему/фичу;
- relevant unit/integration/differential tests зелёные;
- ASAN/UBSAN не находят ошибок для изменённого пути;
- нет unbounded allocation по client-controlled length;
- добавлена/обновлена документация протокольного поведения;
- React browser test проходит без NGINX-specific branch.

## Стиль C

- следовать стилю NGINX;
- использовать `ngx_palloc/ngx_pcalloc` для request-lifetime allocations;
- проверять overflow до арифметики размеров;
- не хранить указатели на входные chain links после возврата caller;
- собственные буферы/links аллоцировать отдельно;
- логировать protocol errors на адекватном уровне без payload/secret metadata.

## Security mindset

Вход браузера недоверенный. Особое внимание:

- malformed base64;
- absurd frame length;
- integer overflow;
- incomplete frame at EOF;
- invalid trailer formatting;
- request smuggling-like header inconsistencies;
- memory amplification;
- slow client / backpressure;
- cancellation during partial frame.

## Как выбирать следующую задачу

Следовать `docs/IMPLEMENTATION_PLAN.md` сверху вниз. Не перескакивать к оптимизациям до корректности unary + trailers + streaming.
