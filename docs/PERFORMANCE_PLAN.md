# M9 — Performance benchmark plan

## Цель

Измерить не только общий throughput gateway, а именно качество **server-side gRPC-Web streaming** при сравнении двух production-like трактов:

```text
A: loadgen -> NGINX -> Envoy grpc_web -> native gRPC backend
B: loadgen -> NGINX + ngx_http_grpc_web_module -> native gRPC backend
```

Дополнительные diagnostic baselines:

```text
C: loadgen -> Envoy grpc_web -> native gRPC backend
D: native gRPC loadgen -> NGINX grpc_pass -> backend
```

Главный вопрос benchmark: сколько одновременных server streams можно обслужить при заданном latency/error SLO и какой CPU/RSS cost приходится на сообщения и переданные байты.

## Основные метрики

Для каждого варианта собирать:

- time to response headers;
- **TTFD** — time to first decoded DATA frame;
- p50/p95/p99/p99.9 inter-DATA arrival latency/jitter;
- stream completion latency;
- messages/s;
- MiB/s и GiB/s полезного protobuf payload;
- wire bytes / payload bytes;
- errors/cancellations/timeouts;
- gateway CPU;
- CPU core-seconds / 1M DATA frames;
- CPU core-seconds / GiB payload;
- RSS и RSS / 100 active streams;
- context switches;
- active connections/streams;
- client-observed backpressure stalls.

HTTP success rate не считается достаточной метрикой: application gRPC status остаётся частью streaming semantics.

## Production A/B topology

Сравнение должно включать именно front NGINX и в legacy path, чтобы не сравнивать `Envoy` напрямую с `NGINX(module)` при другой топологии:

```text
                    +-> NGINX legacy -> Envoy -> backend
load generator -----|
                    +-> NGINX native(module) -> backend
```

Одинаковыми должны быть:

- host/kernel;
- CPU quota/affinity;
- NGINX version и worker count;
- TLS mode;
- backend;
- payload;
- request metadata;
- stream count/rate;
- network placement;
- warmup/measurement duration.

## Базовые streaming profiles

| Profile | DATA payload | Rate / stream | Concurrency sweep | Основной bottleneck |
|---|---:|---:|---:|---|
| tiny/chatty | 256 B | 50 msg/s | 1..1000+ | per-frame CPU/syscalls |
| typical | 4 KiB | 20 msg/s | 1..1000+ | общий production baseline |
| medium | 32 KiB | 10 msg/s | 1..500+ | encode/copy + concurrency |
| heavy | 256 KiB | 5 msg/s | 1..200+ | bandwidth/memory |
| large-payload | **1 / 4 / 8 MiB** | controlled | 1 / 4 / 16+ | Base64, memcpy, memory bandwidth |
| slow consumer | 32 KiB–4 MiB | producer > consumer | 1..100+ | backpressure/RSS |
| saturation | 32 KiB | maximum sustainable | staircase | capacity limit |

## Large-payload server-streaming profile

Large payload должен генерироваться **на backend**, а не передаваться целиком в request. Иначе benchmark одновременно измеряет огромный grpc-web request decode и искажает стоимость server-side response streaming.

`StreamRequest.response_payload_bytes` задаёт точный размер строки в `EchoReply.message`.

### CI regression

Обычный CI использует ограниченный deterministic case:

```text
transport: grpc-web-text
DATA frames: 2
payload per message: 4 MiB
backend delay: 250 ms
```

Критерии:

- оба complete DATA frame доставлены;
- каждый protobuf payload byte-exact;
- trailer `grpc-status: 0` сохранён;
- первый DATA приходит до завершения RPC;
- пауза между DATA наблюдаема, то есть весь stream не буферизуется до EOF.

Этот тест является regression gate корректности, а не абсолютным performance benchmark.

### Performance sweep

В отдельном perf-run:

```text
payload_bytes: 1 MiB, 4 MiB, 8 MiB
messages_per_stream: 8
concurrency: 1, 4, 16, затем staircase до SLO limit
transport: grpc-web-text primary
transport: grpc-web binary diagnostic baseline
```

Для каждого размера и concurrency сравнивать A/B минимум по:

- TTFD p50/p95/p99;
- DATA arrival jitter p99;
- useful MiB/s;
- CPU core-seconds / GiB;
- peak RSS;
- RSS / active stream;
- wire amplification;
- error rate.

Binary diagnostic baseline нужен для отделения стоимости Base64 от стоимости самого proxy path.

### Почему нужны 1 / 4 / 8 MiB

- 1 MiB показывает начало bandwidth-sensitive режима;
- 4 MiB — практический multi-megabyte payload и CI regression size;
- 8 MiB усиливает Base64/memcpy/memory-bandwidth cost и помогает увидеть точку, где выигрыш от удаления Envoy может уменьшаться относительно мелких DATA frames.

8 MiB не следует помещать в обязательный PR CI benchmark: такие результаты слишком чувствительны к shared-runner noise. Он относится к controlled perf environment.

## Concurrency staircase

Для каждого основного profile:

```text
10 -> 25 -> 50 -> 100 -> 200 -> 400 -> 800 -> ...
```

или более плотная последовательность около точки деградации.

На каждой ступени фиксировать p99 TTFD, p99 DATA jitter, CPU, RSS, throughput и error rate.

Главный capacity result:

> max concurrent server streams while all configured SLO limits remain satisfied.

Пример SLO для начала измерений, не release contract:

```text
p99 TTFD < 100 ms + intentional backend delay
p99 gateway-added DATA stall < 20 ms for typical payload
errors < 0.1%
no monotonic RSS growth with completed streams
```

Порог должен быть адаптирован к реальному application SLO до итогового сравнения.

## Slow consumer / backpressure

Отдельно проверять producer быстрее consumer. Нужны:

- bounded RSS;
- отсутствие whole-stream buffering;
- отсутствие потери/перестановки DATA;
- восстановление normal latency после завершения slow streams;
- одинаковый downstream throughput limit для A/B.

Текущий M5 RSS regression остаётся correctness gate; M9 добавляет количественное сравнение RSS/CPU under load.

## Benchmark hygiene

Предпочтительный стенд:

```text
host A: load generator
host B: gateway under test
host C: backend
```

Если используется один host, процессы закрепляются за разными CPU sets/cgroups.

Каждая точка:

- warmup;
- measurement window;
- минимум 5 повторов;
- чередование A/B/B/A либо randomized order;
- одинаковый backend seed/payload;
- результаты сохраняются в raw JSON до построения отчёта.

Python/httpx остаётся удобным для correctness regression, но saturation benchmark должен использовать специализированный Go/Rust load generator, чтобы Python runtime не стал bottleneck раньше gateway.

## Итоговый отчёт

Минимальная сводная таблица:

| Metric | NGINX -> Envoy | NGINX module | Delta |
|---|---:|---:|---:|
| p99 TTFD | | | |
| p99 DATA jitter | | | |
| max streams @ SLO | | | |
| messages/s | | | |
| MiB/s | | | |
| CPU / 1M messages | | | |
| CPU / GiB | | | |
| peak RSS | | | |
| RSS / 100 streams | | | |
| 4 MiB p99 TTFD | | | |
| 8 MiB MiB/s | | | |

Для решения о замене Envoy наиболее важны три итоговых показателя:

1. p99 gateway-added latency/stall per DATA frame;
2. max concurrent server streams при заданном SLO;
3. CPU core-seconds на сообщения и GiB streamed payload.
