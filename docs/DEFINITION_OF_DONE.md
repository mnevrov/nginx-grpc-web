# Definition of Done

Production-ready v0.1 требует выполнения всех пунктов.

## Functional

- [ ] Binary unary работает с существующим grpc-web client.
- [ ] Text unary работает.
- [ ] Text server-streaming работает.
- [ ] Metadata не теряется.
- [ ] Custom trailers поддерживаются.
- [ ] `grpc-status`/`grpc-message` корректны.
- [ ] Trailers-only корректны.
- [ ] Cancellation корректно закрывает upstream.
- [ ] Backend failure не выдаёт клиенту неожиданный HTML success path.

## Seamless React migration

- [ ] Одинаковый React build проходит через Envoy и NGINX.
- [ ] Нет `if (gateway === nginx)` или аналогов.
- [ ] Переключение выполняется route/config change.
- [ ] Порядок `data/status/end/error` совместим.

## Streaming

- [ ] Первое событие доступно до завершения stream.
- [ ] Нет whole-response buffering.
- [ ] 1000-event soak не показывает линейного удержания всей истории.
- [ ] Slow client не приводит к бесконтрольному росту memory.

## Robustness

- [ ] Arbitrary base64 fragmentation tests.
- [ ] Arbitrary frame-header fragmentation tests.
- [ ] Malformed base64 rejection.
- [ ] Incomplete frame EOF handling.
- [ ] Oversized length rejection.
- [ ] Integer overflow checks.
- [ ] ASAN clean.
- [ ] UBSAN clean.

## Compatibility

- [ ] NGINX stable matrix.
- [ ] NGINX mainline matrix.
- [ ] GCC.
- [ ] Clang.
- [ ] Chromium.
- [ ] Firefox or documented exception.
- [ ] WebKit or documented exception.

## Operations

- [ ] Module can be disabled with one directive.
- [ ] Rollback to Envoy documented.
- [ ] Logs identify protocol failures without leaking message payloads.
- [ ] Metrics/logging strategy documented.
- [ ] No mandatory CORS/auth behavior embedded into module.
