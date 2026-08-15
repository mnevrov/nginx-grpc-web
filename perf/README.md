# M9 performance suite

Этот каталог предназначен для количественного сравнения **server-side gRPC-Web streaming**:

```text
legacy: loadgen -> NGINX -> Envoy grpc_web -> native gRPC backend
native: loadgen -> NGINX + ngx_http_grpc_web_module -> native gRPC backend
```

Perf suite не заменяет `tests/protocol`: correctness остаётся отдельным gate, а здесь измеряются latency/capacity/CPU/RSS.

## Быстрый smoke

```bash
make perf-smoke
```

Smoke поднимает оба gateway path, выполняет короткий text-mode stream и создаёт raw JSON + Markdown report. CI запускает этот режим только для проверки работоспособности benchmark harness. **Цифры GitHub-hosted runner нельзя использовать как итоговый benchmark.**

## Основные профили

```bash
make perf-typical   # 4 KiB, concurrency staircase
make perf-large     # 1/4/8 MiB, text + binary, concurrency 1/4/16
make perf-slow      # slow consumer/backpressure
```

Результаты по умолчанию сохраняются в:

```text
perf/results/<UTC timestamp>/
```

Можно указать каталог явно:

```bash
PERF_OUTPUT_DIR=/data/bench/run-001 make perf-large
```

## Large payload

`perf-large` выполняет A/B/B/A для каждой точки:

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

`sample-stats.sh` снимает Docker CPU% и memory usage только для gateway containers текущего path:

```text
native: native-nginx
legacy: legacy-nginx + envoy
```

`report.py` суммирует CPU legacy-пары и оценивает:

```text
CPU core-seconds ~= avg(sum(container CPU%)) / 100 * wall_seconds
CPU core-seconds / GiB = core-seconds / useful payload GiB
```

Peak RSS для legacy также считается как сумма NGINX + Envoy в одном sample.

Для короткого smoke sampling слишком грубый; CPU/GiB имеет смысл на достаточно длинных dedicated-host runs.

## Fair benchmark rules

Для результата, на основании которого принимается архитектурное решение:

1. loadgen, gateway и backend желательно разнести на три host-а;
2. либо закрепить процессы/containers на разных CPU sets;
3. использовать одинаковый NGINX version и worker count;
4. одинаково задать сетевой путь, TLS mode и MTU;
5. делать warmup и минимум 5 повторов;
6. чередовать A/B/B/A или randomize order;
7. сохранять raw JSON до любой агрегации;
8. отдельно следить, чтобы load generator CPU не стал bottleneck.

### CPU budget

Есть два полезных режима:

- **cost mode**: без artificial CPU quotas, сравнивается фактически потреблённый aggregate CPU;
- **capacity mode**: обе архитектуры получают одинаковый суммарный CPU budget; для legacy этот budget делится между NGINX и Envoy.

Их нельзя смешивать в одной итоговой capacity цифре.

## Downstream HTTP version

Текущий автоматизированный perf topology использует cleartext HTTP/1.1 между Go loadgen и front NGINX. Это намеренный первый controlled baseline для стоимости grpc-web filter/proxy path.

Production React обычно приходит через TLS/HTTP/2. TLS/H2 нужно прогонять отдельной topology variant перед финальным production capacity claim; нельзя выдавать HTTP/1.1 result за полную browser/TLS capacity certification.

## Файлы

```text
perf/
├── docker-compose.perf.yml
├── envoy.yaml
├── nginx-legacy.conf
├── nginx-native.conf
├── loadgen/
│   ├── go.mod
│   ├── main.go
│   ├── main_test.go
│   └── protocol.go
├── run-ab.sh
├── sample-stats.sh
├── report.py
└── scenarios/
    └── large-payload.yaml
```

## Report

Каждый run создаёт:

```text
*.json       raw loadgen result
*.stats.tsv  raw Docker CPU/RSS samples
report.json  aggregated machine-readable comparison
report.md    human-readable A/B table
```

Основные decision metrics:

1. p99 `backend_to_client_ms` delta;
2. max concurrent streams при согласованном SLO;
3. CPU core-seconds / GiB и / message;
4. p99 TTFD;
5. peak RSS / active streams;
6. error rate.
