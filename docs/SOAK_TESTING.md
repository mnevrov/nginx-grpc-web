# M13 — Server-streaming soak / production readiness

M13 проверяет не максимальную пропускную способность, а **долговременную устойчивость** native gateway:

```text
browser-like loadgen
  ↓ TLS + HTTP/2 + gRPC-Web text
NGINX + ngx_http_grpc_web_module
  ↓ native gRPC
backend
```

Цель — обнаружить медленные утечки памяти и lifecycle-дефекты, которые не видны в коротких correctness/performance тестах.

## Что именно проверяется

Один `native-nginx` master/worker живёт на протяжении всего теста. На нём последовательно и многократно выполняются:

1. **steady streams** — обычные длительные server-side streams;
2. **churn** — большое количество коротких stream lifecycle;
3. **cancel/reconnect** — клиент отменяет каждый RPC после заданного DATA frame;
4. **backend hard restart** — backend принудительно перезапускается во время активных RPC;
5. **transport reset** — raw HTTP/2 fault backend разрывает upstream stream;
6. **recovery probes** — после каждого disruption и в самом конце выполняется здоровый RPC.

NGINX RSS снимается непрерывно через cgroup v2. Дополнительно фиксируются master PID и Docker `RestartCount` до/после теста.

## Почему memory slope, а не только before/after

Короткий тест может случайно закончиться после освобождения части allocator arenas и скрыть постепенное накопление памяти. Поэтому M13 после warmup строит least-squares trend:

```text
RSS slope = MiB/hour
```

Отдельно сохраняются:

- RSS growth от первого до последнего sample после warmup;
- peak process RSS;
- peak cgroup `memory.current`.

`memory.current` не называется RSS: он включает page cache и другую память cgroup.

## Release-quality strict run

Strict run наследует controlled-host требования M12:

- Linux cgroup v2;
- `PERF_GATEWAY_CPUSET`;
- `PERF_BACKEND_CPUSET`;
- `PERF_LOADGEN_CPUSET`;
- все CPU должны быть online;
- три CPU set не должны пересекаться;
- host preflight должен быть `valid=true`.

Пример:

```bash
PERF_GATEWAY_CPUSET=2-5 \
PERF_BACKEND_CPUSET=6-7 \
PERF_LOADGEN_CPUSET=8-9 \
SOAK_OUTPUT_DIR=/data/bench/soak-2h \
make perf-soak
```

По умолчанию strict policy требует **минимум 2 часа**:

```json
{
  "min_duration_seconds": 7200,
  "min_samples": 240,
  "warmup_seconds": 300,
  "max_rss_slope_mib_per_hour": 8.0,
  "max_rss_growth_mib": 64.0,
  "max_peak_rss_mib": null
}
```

Эти лимиты являются исходным release gate проекта, а не универсальным SLO для любого production host. После первых controlled прогонов threshold можно ужесточить на основании стабильного baseline, но не ослаблять только ради прохождения конкретного run.

Для финального production-readiness решения рекомендуется отдельный **8-часовой** run:

```bash
PERF_GATEWAY_CPUSET=2-5 \
PERF_BACKEND_CPUSET=6-7 \
PERF_LOADGEN_CPUSET=8-9 \
SOAK_DURATION_SECONDS=28800 \
SOAK_OUTPUT_DIR=/data/bench/soak-8h \
make perf-soak
```

## Нагрузочные параметры

Основные параметры можно менять независимо от policy:

```text
SOAK_STEADY_STREAMS
SOAK_STEADY_MESSAGES
SOAK_STEADY_DELAY_MS
SOAK_STEADY_PAYLOAD_BYTES

SOAK_CHURN_STREAMS
SOAK_CHURN_MESSAGES
SOAK_CHURN_DELAY_MS

SOAK_CANCEL_STREAMS
SOAK_CANCEL_MESSAGES
SOAK_CANCEL_AFTER
SOAK_CANCEL_DELAY_MS

SOAK_RESTART_STREAMS
SOAK_RESTART_MESSAGES
SOAK_RESTART_DELAY_MS
SOAK_RESTART_AFTER_SECONDS
SOAK_RESTART_EVERY_CYCLES

SOAK_RESET_STREAMS
SOAK_STATS_INTERVAL
```

При увеличении payload важно сохранять достаточную длительность stream, чтобы backend restart попадал в активный RPC.

## Backend restart semantics

Perf backend в M13 имеет `stop_grace_period: 0s`. Это намеренно: обычный Docker restart даёт процессу до 10 секунд на graceful shutdown, и короткие benchmark streams могут успеть успешно завершиться — тогда disruption фактически не проверяется.

M13 требует одновременно:

```text
backend_restart.observed_disruption = true
backend_restart.inflight_errors > 0
backend_restart.recovery_success = true
```

То есть тест считается валидным только если hard restart действительно оборвал активный RPC и gateway после этого восстановился.

## Client cancellation semantics

Perf loadgen поддерживает:

```bash
-cancel-after N
```

После N полностью декодированных DATA frames клиент отменяет request context и закрывает downstream body. Это считается **ожидаемым cancellation**, а не ошибкой.

Однако итоговый gate требует:

```text
observed_cancellations == expected_cancellations
unexpected_errors == 0
```

Поэтому cancellation mode не может скрыть произвольный transport/application failure.

## Transport reset

Отдельный TLS/H2 listener того же `native-nginx` направлен на deterministic raw HTTP/2 fault backend. По умолчанию тот отдаёт один корректный DATA и затем делает `RST_STREAM`.

M13 считает ожидаемые reset failures и требует точного совпадения:

```text
observed_failures == expected_failures
transport_reset.recovery_success = true
```

После fault batch всегда выполняется healthy RPC через обычный backend.

## Worker/container lifecycle

Перед нагрузкой сохраняются:

```text
nginx master PID
Docker RestartCount
```

В конце оба значения должны остаться неизменными. Самопроизвольный worker/master/container restart не маскируется успешным final probe.

## Результаты

Каталог M13 содержит:

```text
soak-policy.json
host.json
manifest.json
nginx.stats.tsv
events.json
cycle-0001/
cycle-0002/
...
soak.json
soak.md
```

Каждый `cycle-NNNN` содержит raw JSON loadgen для steady/churn/cancel/reset и, когда запланирован restart, in-flight backend-restart run.

`soak.json` — machine-readable source of truth. Основные поля:

```text
evidence_class
verdict
mechanics_pass
reasons
sample_count
duration_seconds
rss.slope_mib_per_hour
rss.growth_mib_after_warmup
rss.peak_mib
events.*
```

## Verdict

Strict controlled run:

```text
soak_pass
soak_fail
```

`soak_pass` возможен только если одновременно прошли duration/sampling, memory trend, cancellation accounting, backend disruption/recovery, transport reset/recovery, final probe и NGINX lifecycle gates.

Shared GitHub runner запускает укороченный `make perf-soak-smoke` только для проверки harness. Такой результат всегда:

```text
evidence_class = harness_only
verdict = inconclusive
```

даже если `mechanics_pass=true` и наблюдаемые цифры выглядят хорошо. CI smoke нельзя использовать как доказательство production memory stability.

## Минимум перед canary rollout

Перед production canary рекомендуется сохранить и привязать к exact commit:

1. M12 controlled TLS/H2 capacity decision;
2. M12 large-payload controlled run (минимум 4 MiB DATA);
3. M13 strict 2-hour soak;
4. M13 8-hour soak для release candidate;
5. `host.json`, policies и все raw artifacts;
6. подтверждение, что ни один run не имел NGINX restart и все disruption recovery gates прошли.

Только после этого performance/soak evidence имеет смысл сопоставлять с canary observability из `docs/ROLLOUT.md`.
