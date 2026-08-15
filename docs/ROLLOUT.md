# Envoy -> NGINX rollout

Цель migration — заменить production datapath

```text
browser -> NGINX -> Envoy grpc_web filter -> native gRPC backend
```

на

```text
browser -> NGINX + ngx_http_grpc_web_module -> native gRPC backend
```

без изменения React/`grpc-web` client.

## Основной принцип

Canary лучше делать **между двумя gateway pools**, а не сложной условной логикой внутри одного NGINX location.

Рекомендуемая схема перехода:

```text
                         +-> legacy gateway pool -> Envoy -> backend
browser -> LB / ingress -|
                         +-> native gateway pool -> NGINX module -> backend
```

Так rollback — это изменение веса обратно на legacy pool. Для возврата не требуется выпуск frontend, срочная перекомпиляция модуля или переписывание NGINX protocol path.

## Stage 0 — baseline

Перед canary минимум 24 часа зафиксировать baseline существующего Envoy path:

- RPC success rate по `grpc-status`;
- distribution application error codes;
- p50/p95/p99 latency;
- time-to-first-DATA для streaming RPC;
- stream completion/cancel rate;
- HTTP 499/5xx;
- upstream resets/timeouts;
- gateway CPU/RSS;
- traffic volume и bytes/stream.

Без baseline сравнение canary бессодержательно.

## Stage 1 — dark validation

До пользовательского трафика:

1. собрать module ровно для production NGINX line;
2. `nginx -t`;
3. поднять отдельный native gateway pool;
4. прогнать synthetic unary/text/stream/failure/cancel checks;
5. прогнать реальный React client против test endpoint;
6. проверить dashboards/logging/alerts;
7. проверить rollback операционно, а не только документально.

Если возможно безопасное shadowing запросов без дублирования side effects, оно может использоваться для read-only RPC. Для mutating RPC traffic mirroring не применять без явной идемпотентности.

## Stage 2 — 1% canary

Перевести примерно 1% реального трафика на native pool.

Gate для продолжения:

- нет новых browser compatibility failures;
- grpc-status distribution статистически совместим с baseline;
- нет роста `UNKNOWN (2)`/transport errors;
- p95/p99 и time-to-first-DATA не хуже согласованного бюджета;
- нет роста worker RSS со временем;
- 499/cancellation semantics не изменились;
- upstream error rate не вырос.

Любая unexplained protocol anomaly — причина остановить rollout, даже если общий HTTP success rate выглядит нормальным.

## Stage 3 — 5-10%

Увеличить долю только после стабильного observation window.

На этой стадии обязательно проверить:

- длинные server streams;
- медленные клиенты;
- peak traffic;
- backend deploy/restart events;
- реальные deadline/cancellation patterns.

## Stage 4 — 25-50%

Основной критерий — не только отсутствие ошибок, но и отсутствие накопительного resource drift.

Смотреть:

- RSS slope по workers;
- connection count;
- CPU per request/byte;
- first-DATA latency;
- reset/timeout rate;
- error distribution по browser/user-agent segments.

## Stage 5 — 100%

После выхода на 100% **не удалять Envoy pool немедленно**.

Рекомендуемый rollback window — несколько релизных циклов/дней эксплуатации в зависимости от критичности сервиса.

Legacy pool должен оставаться:

- синхронизированным по routing/backend targets;
- доступным health checks;
- готовым принять 100% traffic без rebuild.

## Rollback triggers

Немедленно возвращать трафик на legacy pool при:

- crash/restart NGINX workers;
- росте malformed/UNKNOWN browser errors;
- ложных successful RPC;
- потере trailers/grpc-status;
- buffering server streams до EOF;
- неконтролируемом RSS growth;
- несовместимости конкретного production browser;
- significant latency regression;
- росте upstream resets, который отсутствует на legacy path.

## Rollback procedure

1. weight native pool -> 0;
2. weight legacy pool -> 100%;
3. убедиться, что новые connections идут через legacy path;
4. не убивать активные native workers/streams без необходимости;
5. сохранить logs/metrics/core dumps/NGINX effective config;
6. зафиксировать точный module artifact checksum и NGINX version;
7. воспроизвести проблему на test harness;
8. только после root-cause analysis начинать новый canary.

Если переключение выполняется конфигурацией самого NGINX, использовать `nginx -t` перед `nginx -s reload`; обычный reload должен позволить старым workers завершить активные connections gracefully.

## Что сравнивать с Envoy

Сравнивать semantic outcome:

- DATA payload sequence;
- trailers/metadata;
- grpc-status/grpc-message;
- event order;
- first-DATA timing;
- cancellation;
- observable gateway failures.

Не использовать как rollout KPI:

- Base64 chunk boundaries;
- TCP packetization;
- HTTP chunk sizes.

Они не являются частью gRPC-Web semantic compatibility contract.
