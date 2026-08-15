# M9/M10/M11 performance suite

Этот каталог предназначен для количественного сравнения **server-side gRPC-Web streaming**:

```text
legacy: loadgen -> NGINX -> Envoy grpc_web -> native gRPC backend
native: loadgen -> NGINX + ngx_http_grpc_web_module -> native gRPC backend
```

Perf suite не заменяет `tests/protocol`: correctness остаётся отдельным gate, а здесь измеряются latency/capacity/CPU/RSS.

## Frontend modes

Доступны два контролируемых downstream режима:

```text
http1   loadgen -> cleartext HTTP/1.1 -> front NGINX
tls-h2  loadgen -> TLS + ALPN h2 -> HTTP/2 -> front NGINX
```

Для `tls-h2` runner генерирует эфемерный CA/server certificate в `perf/.certs/`, использует один и тот же сертификат для legacy/native и требует от каждого measured stream:

- успешную проверку benchmark CA;
- HTTPS;
- `response.ProtoMajor == 2`;
- ALPN `h2`;
- TLS 1.2 или TLS 1.3.

Silent fallback на HTTP/1.1 считается ошибкой benchmark, а не допустимым sample. NGINX TLS listener использует `http2 on;`, то есть современную server-level директиву HTTP/2. CA private key удаляется сразу после подписи server certificate.

## Быстрые smoke gates

```bash
make perf-smoke      # HTTP/1.1 baseline
make perf-h2-smoke   # TLS/HTTP2 strict baseline
```

Оба smoke поднимают legacy/native gateway paths и создают raw JSON + Markdown report. CI запускает их только для проверки benchmark harness. **Цифры GitHub-hosted runner нельзя использовать как итоговый benchmark.**

## Capacity / SLO staircase

M11 добавляет поиск **max sustainable streams @ SLO**. На каждой ступени concurrency выполняется A/B/B/A, после чего обе архитектуры отдельно классифицируются по SLO.

```bash
PERF_CAPACITY_SLO=/data/slo.json \
PERF_CAPACITY_STEPS=10,25,50,100,200,400,800 \
make perf-capacity

PERF_CAPACITY_SLO=/data/slo.json \
PERF_CAPACITY_STEPS=10,25,50,100,200,400,800 \
make perf-h2-capacity
```

Поддерживаемые SLO limits:

```json
{
  "max_error_rate": 0.001,
  "max_p99_backend_to_client_ms": 75.0,
  "max_p99_ttfd_ms": 250.0,
  "max_avg_gateway_cores": 3.5,
  "max_peak_rss_mib": 1024.0
}
```

Это только пример структуры, не рекомендуемые production thresholds. Реальные значения должны исходить из SLO сервиса.

Capacity определяется как последняя **непрерывно проходящая** ступень от минимальной нагрузки. Если после первого failed point более высокая ступень случайно проходит из-за шума, она не увеличивает `max_sustainable_streams`.

Для equal-budget capacity run можно закрепить gateway архитектуры на одном CPU set:

```bash
PERF_GATEWAY_CPUSET=2-5 \
PERF_BACKEND_CPUSET=6-7 \
PERF_CAPACITY_SLO=/data/slo.json \
make perf-h2-capacity
```

`native-nginx`, `legacy-nginx` и `envoy` получают один и тот же `PERF_GATEWAY_CPUSET`; legacy NGINX и Envoy делят этот набор CPU, поэтому дополнительный Envoy hop не получает скрытый второй CPU budget.

Capacity run создаёт обычные raw perf artifacts плюс:

```text
capacity.json
capacity.md
```

Если `first_failed_streams == null`, предел не достигнут: последняя tested ступень прошла, и staircase нужно продолжить выше.

Подробная методика: [`docs/CAPACITY_BENCHMARKS.md`](../docs/CAPACITY_BENCHMARKS.md).

CI `perf-capacity-smoke` запускает только ступени `1,2` с намеренно широкими limits для `http1` и `tls-h2`. Это gate механики, а не production capacity measurement.

## Основные профили

HTTP/1.1:

```bash
make perf-typical
make perf-large
make perf-slow
```

TLS/HTTP2:

```bash
make perf-h2-typical
make perf-h2-large
make perf-h2-slow
```

Результаты по умолчанию сохраняются в:

```text
perf/results/<UTC timestamp>-<frontend>/
```

Можно указать каталог явно:

```bash
PERF_OUTPUT_DIR=/data/bench/h2-large-001 make perf-h2-large
```

## Large payload

`perf-large` и `perf-h2-large` выполняют A/B/B/A для каждой точки:

```text
transport: grpc-web-text, grpc-web binary
payload:   1 MiB, 4 MiB, 8 MiB per DATA message
messages:  8 per stream
streams:   1, 4, 16
```

Большой payload создаётся backend-ом через `response_payload_bytes`; request остаётся маленьким и не загрязняет measurement стоимостью multi-MiB request decode.

Binary mode нужен как diagnostic baseline: разница `text - binary` показывает цену Base64/текстового grpc-web path, а разница `legacy - native` — цену дополнительного NGINX -> Envoy hop и Envoy filter path.

## Метрики load generator

Go loadgen сохраняет:

- frontend mode;
- negotiated HTTP protocol;
- TLS version и ALPN для HTTPS;
- response-header latency;
- TTFD до первого **полностью декодированного DATA frame**;
- inter-DATA arrival intervals;
- backend-relative `backend_to_client_ms` для каждого DATA;
- stream duration;
- DATA count;
- useful payload bytes;
- HTTP body wire bytes;
- gRPC status/errors;
- aggregate messages/s и MiB/s.

`include_server_timing` включается только benchmark request-ом. Backend ставит `server_elapsed_ns` непосредственно перед `yield` в `grpc.aio`. Поэтому `backend_to_client_ms` включает protobuf serialization + native gRPC transport + gateway + downstream delivery. Backend одинаков для A/B, поэтому наиболее важен **delta между архитектурами**, а не абсолютное число.

## CPU / RSS

`sample-stats.sh` читает **cgroup v2** counters gateway containers с host-а:

```text
native: native-nginx
legacy: legacy-nginx + envoy
```

Для каждого container сохраняются три независимые величины:

```text
cpu_usage_usec        cumulative cpu.stat:usage_usec
rss_bytes             сумма VmRSS всех PID из cgroup.procs
memory_current_bytes  cgroup memory.current
```

Измерение через host cgroup принципиально лучше для коротких streaming runs, чем `docker stats --no-stream`: нет ~1 s задержки sampler-а и не запускаются дополнительные процессы внутри измеряемого container.

`report.py` считает:

```text
CPU core-seconds = Σ(last usage_usec - first usage_usec) / 1_000_000
CPU core-seconds / GiB = core-seconds / useful payload GiB
```

Capacity evaluator дополнительно использует:

```text
error_rate = failed streams / requested streams
avg_gateway_cores = CPU core-seconds / wall seconds
```

Для legacy CPU и memory метрики суммируются по front NGINX + Envoy. **Peak RSS** — максимальная во времени сумма process `VmRSS`. `memory.current` хранится отдельно как `peak_cgroup_memory_mib`, потому что включает page cache и другую память, списанную на cgroup, и не должна называться RSS.

Каждый measured run обязан иметь минимум два cgroup sample; иначе report завершается ошибкой вместо публикации нулевых CPU/RSS.

Требование perf host: Linux cgroup v2 с доступным `/proc/<container-pid>/cgroup` и `/sys/fs/cgroup`.

## Fair benchmark rules

Для результата, на основании которого принимается архитектурное решение:

1. loadgen, gateway и backend желательно разнести на три host-а;
2. либо закрепить процессы/containers на разных CPU sets;
3. использовать одинаковый NGINX version и worker count;
4. одинаково задать сетевой путь, TLS mode и MTU;
5. сравнивать legacy/native внутри **одного frontend mode**;
6. делать warmup и минимум 5 независимых полных повторов для release-quality вывода;
7. внутри каждой capacity ступени использовать A/B/B/A;
8. сохранять raw JSON до любой агрегации;
9. отдельно следить, чтобы load generator CPU не стал bottleneck.

Автоматический runner сначала прогревает оба gateway path маленьким discarded stream, затем начинает measured A/B runs. Для `tls-h2` этот warmup также проверяет CA/ALPN/HTTP2 до первого measured sample. Cgroup sampler обязан записать baseline до старта loadgen и финальный sample после его завершения.

### CPU budget

Есть два полезных режима:

- **cost mode**: без artificial CPU quotas, сравнивается фактически потреблённый aggregate CPU;
- **capacity mode**: обе архитектуры получают одинаковый суммарный CPU budget; для legacy этот budget делится между NGINX и Envoy.

Их нельзя смешивать в одной итоговой capacity цифре.

## TLS/H2 interpretation

TLS/H2 profile добавляет реальные TLS record/crypto и HTTP/2 framing/multiplexing costs на участке loadgen → front NGINX. Он не меняет upstream архитектуру:

```text
native: front NGINX --native HTTP/2 gRPC--> backend
legacy: front NGINX --HTTP/1.1--> Envoy --native HTTP/2 gRPC--> backend
```

Поэтому для production решения нужны как минимум две группы результатов:

1. `http1` — controlled proxy/filter baseline;
2. `tls-h2` — browser-like transport baseline.

TLS/H2 Go loadgen всё ещё не является literal browser certification. Browser compatibility остаётся отдельным Playwright gate на Chromium/Firefox/WebKit.

## Файлы

```text
perf/
├── capacity.py
├── docker-compose.perf.yml
├── envoy.yaml
├── generate-tls.sh
├── nginx-legacy.conf
├── nginx-native.conf
├── loadgen/
│   ├── go.mod
│   ├── http_transport.go
│   ├── main.go
│   ├── main_test.go
│   └── protocol.go
├── run-ab.sh
├── sample-stats.sh
├── report.py
├── test_capacity.py
└── scenarios/
    ├── capacity-smoke-slo.json
    └── large-payload.yaml
```

## Report

Обычный performance run создаёт:

```text
*.json       raw loadgen result
*.stats.tsv  raw cgroup CPU/RSS/cgroup-memory samples
report.json  aggregated machine-readable comparison
report.md    human-readable A/B table
```

Capacity run дополнительно создаёт:

```text
capacity.json  machine-readable SLO classification
capacity.md    sustainable capacity + staircase table
```

`frontend` является частью scenario key, поэтому результаты `http1` и `tls-h2` не смешиваются даже при использовании общего output directory. `report.json` дополнительно сохраняет наблюдаемые `http_protocols`, `tls_alpn` и `tls_versions`.

Основные decision metrics:

1. max sustainable concurrent streams при согласованном SLO;
2. p99 `backend_to_client_ms` delta;
3. CPU core-seconds / GiB и average gateway cores;
4. p99 TTFD;
5. peak RSS;
6. error rate.
