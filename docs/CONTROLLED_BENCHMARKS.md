# M12 — Controlled-host benchmark & architecture decision

M12 предназначен не для очередного CI smoke, а для получения защищаемого количественного ответа:

> насколько `NGINX + ngx_http_grpc_web_module` выгоднее или хуже production-like тракта `NGINX -> Envoy` для server-side gRPC-Web streaming при одинаковом resource budget.

## Что считается controlled evidence

`decision.md` может получить рекомендацию `native_preferred` только когда каждый repeat прошёл strict host preflight.

Strict preflight требует:

- Linux cgroup v2;
- заданный `PERF_GATEWAY_CPUSET`;
- заданный `PERF_BACKEND_CPUSET`;
- заданный `PERF_LOADGEN_CPUSET`;
- отсутствие пересечения gateway/backend/loadgen CPU sets;
- одинаковый host fingerprint во всех repeats.

`run-controlled.sh` запускает весь benchmark controller через `taskset` на `PERF_LOADGEN_CPUSET`. Gateway containers получают `PERF_GATEWAY_CPUSET`, backend container — `PERF_BACKEND_CPUSET`. Это не позволяет load generator отъедать CPU budget измеряемого gateway.

CPU governor сохраняется в host snapshot. Режим, отличный от `performance`, пока является warning, а не hard error: на виртуализированных/managed host governor может быть недоступен или не контролироваться гостевой ОС.

Shared GitHub runner запускает тот же workflow с `PERF_CONTROLLED_STRICT=0`. Такой результат всегда получает:

```text
evidence_class = harness_only
recommendation = inconclusive
```

даже если случайные CI цифры визуально показывают выигрыш native path.

## Host fingerprint

Каждый repeat содержит `host.json`. Fingerprint вычисляется по стабильным полям:

- kernel release;
- machine architecture;
- CPU model;
- online CPU set;
- total RAM;
- Docker server version;
- cgroup version;
- gateway/backend/loadgen CPU sets;
- CPU governors.

Timestamp и hostname в fingerprint не входят, поэтому перенос результата между каталогами или изменение имени host не создают ложную несовместимость.

## Минимальный release-quality run

Сначала создайте реальный SLO JSON. Пример структуры:

```json
{
  "max_error_rate": 0.001,
  "max_p99_backend_to_client_ms": 75.0,
  "max_p99_ttfd_ms": 250.0,
  "max_avg_gateway_cores": 3.5,
  "max_peak_rss_mib": 1024.0
}
```

Значения выше — только пример формата. Thresholds должны исходить из требований конкретного сервиса.

Основной production-like benchmark:

```bash
PERF_FRONTEND=tls-h2 \
PERF_GATEWAY_CPUSET=2-5 \
PERF_BACKEND_CPUSET=6-7 \
PERF_LOADGEN_CPUSET=8-11 \
PERF_CAPACITY_SLO=/data/grpc-web-slo.json \
PERF_CAPACITY_STEPS=25,50,100,200,400,800,1200 \
PERF_CONTROLLED_REPEATS=5 \
PERF_CONTROLLED_OUTPUT_DIR=/data/bench/typical-h2 \
bash ./perf/run-controlled.sh
```

Каждый repeat самостоятельно выполняет M11 A/B/B/A staircase. После всех repeats M12 агрегирует результаты и создаёт архитектурный decision.

## Large payload — 4 MiB per DATA

Для основного multi-megabyte server-streaming case:

```bash
PERF_FRONTEND=tls-h2 \
PERF_GATEWAY_CPUSET=2-5 \
PERF_BACKEND_CPUSET=6-7 \
PERF_LOADGEN_CPUSET=8-11 \
PERF_CAPACITY_SLO=/data/grpc-web-large-slo.json \
PERF_CAPACITY_PAYLOAD_BYTES=4194304 \
PERF_CAPACITY_MESSAGES=8 \
PERF_CAPACITY_DELAY_MS=50 \
PERF_CAPACITY_STEPS=1,2,4,8,16,32,64 \
PERF_CONTROLLED_REPEATS=5 \
PERF_CONTROLLED_OUTPUT_DIR=/data/bench/large-4m-h2 \
bash ./perf/run-controlled.sh
```

Backend генерирует payload сам; request остаётся маленьким. Поэтому benchmark измеряет server response path, а не одновременно multi-MiB request decode.

Для 8 MiB замените:

```bash
PERF_CAPACITY_PAYLOAD_BYTES=8388608
```

и при необходимости уменьшите staircase.

## Slow consumer / backpressure

```bash
PERF_FRONTEND=tls-h2 \
PERF_GATEWAY_CPUSET=2-5 \
PERF_BACKEND_CPUSET=6-7 \
PERF_LOADGEN_CPUSET=8-11 \
PERF_CAPACITY_SLO=/data/grpc-web-slow-slo.json \
PERF_CAPACITY_PAYLOAD_BYTES=32768 \
PERF_CAPACITY_MESSAGES=20 \
PERF_CAPACITY_DELAY_MS=1 \
PERF_CAPACITY_CONSUMER_DELAY_MS=25 \
PERF_CAPACITY_STEPS=5,10,25,50,100,200 \
PERF_CONTROLLED_REPEATS=5 \
PERF_CONTROLLED_OUTPUT_DIR=/data/bench/slow-h2 \
bash ./perf/run-controlled.sh
```

## Структура результата

```text
/data/bench/typical-h2/
├── manifest.json
├── slo.json
├── decision-policy.json
├── repeat-01/
│   ├── host.json
│   ├── *.json
│   ├── *.stats.tsv
│   ├── report.json
│   ├── report.md
│   ├── capacity.json
│   └── capacity.md
├── repeat-02/
│   └── ...
├── ...
├── decision.json
└── decision.md
```

`manifest.json` фиксирует commit, NGINX version/compiler, frontend, repeat count, CPU sets и scenario parameters.

## Как строится итоговый decision

### Capacity

Для каждой архитектуры сохраняются:

- min;
- median;
- max;
- coefficient of variation (CV).

Итоговый capacity delta считается по медианам:

```text
(native median - legacy median) / legacy median
```

При CV выше policy threshold результат становится `inconclusive` независимо от средней выгоды.

### Same-load comparison

CPU/RSS/latency нельзя честно сравнивать, если legacy измеряется на 100 streams, а native на 400.

Поэтому M12 выбирает conservative common reference load:

```text
minimum sustainable capacity across both architectures and all repeats
```

На этой одной и той же ступени для каждого repeat сравниваются:

- p99 TTFD;
- p99 backend -> client DATA latency;
- average gateway CPU cores;
- peak RSS;
- error rate.

В decision попадает медиана per-repeat delta.

## Default decision policy

`perf/scenarios/decision-default.json` по умолчанию требует:

- минимум 5 repeats;
- capacity CV <= 20%;
- material benefit хотя бы по одному критерию:
  - native capacity +10% или больше;
  - CPU saving 10% или больше;
  - RSS saving 10% или больше;
- p99 TTFD regression не более 5%;
- p99 backend-to-client regression не более 5%.

Только при выполнении stability + latency guardrails + material benefit и strict controlled evidence вывод становится:

```text
native_preferred
```

Во всех остальных случаях workflow выбирает более безопасный результат:

```text
inconclusive
```

Он намеренно не пытается автоматически объявлять `legacy_preferred`: отрицательный результат должен быть разобран по raw artifacts и конкретным violated guardrails.

## Что сохранить для архитектурного решения

Для каждого финального прогона храните:

1. весь output directory без удаления raw JSON/TSV;
2. точный Git commit;
3. SLO и decision policy snapshots;
4. host fingerprint/preflight;
5. `decision.json` и `decision.md`;
6. отдельно результаты typical, 4 MiB/8 MiB и slow-consumer сценариев.

Итоговая архитектурная рекомендация должна ссылаться минимум на production-like `tls-h2` typical и large-payload результаты. HTTP/1 можно сохранить как диагностический baseline, но не использовать вместо TLS/H2 production-like evidence.
