# Capacity / SLO benchmarks

M11 ищет не «максимальное число подключений вообще», а **максимальную устойчивую concurrency при заранее заданном SLO**.

Сравниваются две архитектуры:

```text
legacy: loadgen -> NGINX -> Envoy grpc_web -> native gRPC backend
native: loadgen -> NGINX + ngx_http_grpc_web_module -> native gRPC backend
```

и два downstream режима:

```text
http1   cleartext HTTP/1.1
tls-h2  TLS + ALPN h2 + HTTP/2
```

## Что считается capacity

Для каждой ступени concurrency выполняется A/B/B/A:

```text
native A1 -> legacy B1 -> legacy B2 -> native A2
```

После ступени агрегируются метрики и отдельно для `legacy` и `native` проверяется SLO.

`max_sustainable_streams` — последняя **непрерывно проходящая** ступень от минимальной нагрузки. Если после первого failed point более высокая ступень случайно проходит из-за шума, она не увеличивает capacity.

Это защищает итог от немонотонного шума benchmark-а.

## SLO

SLO задаётся JSON-файлом. Поддерживаются поля:

```json
{
  "max_error_rate": 0.001,
  "max_p99_backend_to_client_ms": 75.0,
  "max_p99_ttfd_ms": 250.0,
  "max_avg_gateway_cores": 3.5,
  "max_peak_rss_mib": 1024.0
}
```

Значения выше — только пример структуры, а не рекомендуемый production SLO. Пороговые значения должны следовать из требований конкретного сервиса.

Поле можно исключить из JSON, если оно не участвует в classification. Хотя бы один limit обязателен.

### Метрики

- `error_rate` = failed streams / requested streams по всем повторам точки;
- `p99_backend_to_client_ms` — backend-relative delivery metric из M9;
- `p99_ttfd_ms` — время до первого полностью декодированного DATA frame;
- `avg_gateway_cores` = суммарные gateway CPU core-seconds / wall seconds;
- `peak_rss_mib` — максимум суммы process RSS соответствующей архитектуры.

Для legacy CPU/RSS включает front NGINX + Envoy. Для native — NGINX с модулем.

## Запуск

HTTP/1:

```bash
PERF_CAPACITY_SLO=/data/slo.json \
PERF_CAPACITY_STEPS=10,25,50,100,200,400,800 \
make perf-capacity
```

TLS/H2:

```bash
PERF_CAPACITY_SLO=/data/slo.json \
PERF_CAPACITY_STEPS=10,25,50,100,200,400,800 \
make perf-h2-capacity
```

Дополнительные параметры:

```text
PERF_CAPACITY_TRANSPORT=text|binary
PERF_CAPACITY_PAYLOAD_BYTES=4096
PERF_CAPACITY_MESSAGES=20
PERF_CAPACITY_DELAY_MS=20
PERF_CAPACITY_CONSUMER_DELAY_MS=0
PERF_OUTPUT_DIR=/data/bench/run-001
```

Ступени должны быть строго возрастающими положительными целыми числами.

## Equal CPU budget

Для capacity-решения архитектуры должны получать одинаковый CPU budget. M11 поддерживает optional CPU-set pinning:

```bash
PERF_GATEWAY_CPUSET=2-5 \
PERF_BACKEND_CPUSET=6-7 \
PERF_CAPACITY_SLO=/data/slo.json \
make perf-h2-capacity
```

`PERF_GATEWAY_CPUSET` применяется одновременно к:

```text
native-nginx
legacy-nginx
envoy
```

То есть legacy NGINX и Envoy **делят один и тот же набор CPU**, равный CPU set native NGINX. Envoy не получает отдельный скрытый CPU budget.

Backend желательно закреплять на другом CPU set, а load generator — запускать на отдельном host или отдельном CPU set вне gateway budget.

## Early stop

После каждой ступени создаются промежуточные `report.json` и `capacity.json`. Runner прекращает дальнейший рост нагрузки, когда обе архитектуры нарушили SLO на текущей ступени.

Даже без early stop итоговая capacity определяется по правилу contiguous pass, поэтому более поздний случайный pass не восстанавливает уже потерянную устойчивость.

## Результаты

Capacity run создаёт обычные perf artifacts плюс:

```text
capacity.json  machine-readable SLO classification
capacity.md    итоговая таблица capacity и staircase
```

`capacity.json` содержит для каждой архитектуры:

- `max_sustainable_streams`;
- `first_failed_streams`;
- все проверенные точки;
- pass/fail каждой точки;
- список нарушенных SLO metrics;
- observed metrics.

Также рассчитывается `capacity_delta_percent`:

```text
(native_capacity - legacy_capacity) / legacy_capacity * 100%
```

## Интерпретация

Если `first_failed_streams` равен `null`, предел **не найден**: последняя ступень прошла и staircase нужно продолжить выше. Последнюю tested concurrency нельзя называть абсолютным максимумом системы.

Если минимальная ступень уже failed, `max_sustainable_streams = 0`. В этом случае сначала нужно проверить корректность SLO, CPU budget и отсутствие bottleneck на backend/loadgen.

Для release-quality вывода нужны:

1. dedicated host-ы или жёсткая CPU isolation;
2. одинаковый NGINX version/worker count;
3. одинаковый downstream frontend mode;
4. одинаковый CPU set для сравниваемого gateway budget;
5. backend вне gateway CPU budget;
6. несколько независимых полных staircase runs;
7. сохранение raw JSON/stats для каждого run;
8. анализ стабильности границы capacity между повторами.

## CI smoke

`capacity-smoke-slo.json` содержит намеренно очень широкие latency/CPU/RSS limits и используется только для проверки benchmark mechanics. CI запускает короткие staircase `1,2` для `http1` и `tls-h2`.

Эти цифры **не являются performance результатом** и не должны использоваться для архитектурного решения.
