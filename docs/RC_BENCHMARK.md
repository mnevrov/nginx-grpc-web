# M15 — Controlled-host RC benchmark

M15 получает первое release-quality количественное сравнение production-like server-side gRPC-Web streaming:

```text
legacy: loadgen -> NGINX -> Envoy -> native gRPC backend
native: loadgen -> NGINX + ngx_http_grpc_web_module -> native gRPC backend
```

M14 уже merged и проверяет provenance/release evidence. M15 не заменяет M14: он производит **controlled performance evidence**, которое затем передаётся в `make release-check` вместе со strict soak evidence.

## Что доказывает M15

Итоговый controlled benchmark должен ответить:

- max sustainable streams @ заданном SLO для legacy/native;
- native capacity delta;
- same-load p99 TTFD и backend→client latency delta;
- same-load gateway CPU delta;
- same-load peak RSS delta;
- error-rate delta;
- стабильность результата по пяти strict repeats;
- поведение typical, 4 MiB и slow-consumer сценариев;
- 8 MiB, если host способен выполнить этот сценарий, либо явную причину skip.

Shared GitHub runner **не** является controlled host. Workflow `rc-benchmark` проверяет только evaluator/shell contract и никогда не запускает release-quality workload.

## Требования к host

`make rc-benchmark` требует Linux host с:

- Docker daemon;
- cgroup v2;
- `taskset`;
- тремя явно заданными и непересекающимися CPU sets;
- clean Git worktree;
- достаточным CPU/RAM для выбранных staircase ceilings.

Пример CPU isolation:

```text
gateway: 2-5
backend: 6-7
loadgen/controller: 8-11
```

`perf/host_info.py --strict` выполняется **до** дорогих benchmark attempts. Все selected scenarios обязаны иметь один и тот же host fingerprint.

## SLO — обязательный внешний вход

M15 намеренно не содержит production SLO thresholds. Оператор предоставляет как минимум три файла:

```text
RC_TYPICAL_SLO
RC_LARGE4M_SLO
RC_SLOW_SLO
```

Формат — тот же `perf/capacity.py`, например:

```json
{
  "max_error_rate": 0.001,
  "max_p99_backend_to_client_ms": 75.0,
  "max_p99_ttfd_ms": 250.0,
  "max_avg_gateway_cores": 3.5,
  "max_peak_rss_mib": 1024.0
}
```

Числа выше показывают только структуру JSON. Они **не являются** рекомендуемым production SLO.

## 8 MiB policy

Нельзя молча не запускать 8 MiB scenario.

Допустимы только два варианта:

```bash
RC_LARGE8M_SLO=/data/slo-large8m.json
```

или явное решение:

```bash
RC_SKIP_LARGE8M_REASON='target host cannot sustain a meaningful 8 MiB staircase within the RC resource budget'
```

Skip reason сохраняется в top-level M15 manifest. Для финального release review это остаётся ручным decision item.

## Основной запуск

```bash
PERF_GATEWAY_CPUSET=2-5 \
PERF_BACKEND_CPUSET=6-7 \
PERF_LOADGEN_CPUSET=8-11 \
RC_TYPICAL_SLO=/data/slo-typical.json \
RC_LARGE4M_SLO=/data/slo-large4m.json \
RC_SLOW_SLO=/data/slo-slow.json \
RC_LARGE8M_SLO=/data/slo-large8m.json \
RC_OUTPUT_DIR=/data/nginx-grpc-web/rc-benchmark \
make rc-benchmark
```

По умолчанию:

```text
repeats:      5
max attempts: 4
NGINX:        1.30.4
compiler:     gcc
frontend:     TLS/H2 only
```

Можно изменить:

```text
RC_REPEATS                 >= 5
RC_MAX_ATTEMPTS
RC_DECISION_POLICY
NGINX_VERSION
BUILD_CC
```

## Сценарии

### Typical

```text
transport:       grpc-web-text
payload:         4096 bytes / DATA
messages:        20
backend delay:   20 ms
initial steps:   25,50,100,200,400,800,1200
ceiling:         5000 streams
```

Настройки:

```text
RC_TYPICAL_STEPS
RC_TYPICAL_MAX_STREAMS
```

### 4 MiB

```text
transport:       grpc-web-text
payload:         4194304 bytes / DATA
messages:        8
backend delay:   50 ms
initial steps:   1,2,4,8,16,32,64
ceiling:         256 streams
```

Настройки:

```text
RC_LARGE4M_STEPS
RC_LARGE4M_MAX_STREAMS
```

### Slow consumer

```text
transport:       grpc-web-text
payload:         32768 bytes / DATA
messages:        20
backend delay:   1 ms
consumer delay:  25 ms
initial steps:   5,10,25,50,100,200
ceiling:         1600 streams
```

Настройки:

```text
RC_SLOW_STEPS
RC_SLOW_MAX_STREAMS
```

### 8 MiB

Если задан `RC_LARGE8M_SLO`:

```text
transport:       grpc-web-text
payload:         8388608 bytes / DATA
messages:        8
backend delay:   50 ms
initial steps:   1,2,4,8,16,32
ceiling:         128 streams
```

Настройки:

```text
RC_LARGE8M_STEPS
RC_LARGE8M_MAX_STREAMS
```

## Почему M15 делает complete attempts

M11 умеет сообщать:

```text
first_failed_streams = null
```

Это означает только lower bound: например, `native >= 1200 streams`. Нельзя сравнивать его как финальную capacity с legacy.

M15 поэтому работает так:

1. выполняет **полный controlled attempt** из минимум пяти repeats;
2. проверяет каждый raw `capacity.json`;
3. если у legacy или native хотя бы в одном repeat не найден первый failed SLO level — attempt сохраняется, но не выбирается;
4. staircase детерминированно расширяется;
5. запускается **новый полный five-repeat attempt**;
6. partial repeats из разных attempts никогда не склеиваются;
7. когда обе boundaries найдены, M12 decision дополнительно обязан быть `native_preferred` без decision reasons;
8. если boundaries найдены, но decision `inconclusive`, M15 завершается ошибкой — расширение staircase не используется для сокрытия отрицательного архитектурного результата.

Если `RC_MAX_ATTEMPTS` или scenario ceiling исчерпан раньше boundary, run fail-closed.

## Структура output

```text
/data/nginx-grpc-web/rc-benchmark/
├── manifest.json
├── preflight.json
├── inputs/
│   ├── typical-slo.json
│   ├── large4m-slo.json
│   ├── slow-slo.json
│   ├── large8m-slo.json        # если выполнялся
│   └── decision-policy.json
├── typical/
│   ├── attempt-01/
│   │   ├── manifest.json
│   │   ├── decision.json
│   │   ├── repeat-01/...
│   │   └── rc-scenario.json
│   ├── attempt-02/...          # если boundary потребовала расширения
│   ├── selected.json
│   ├── selected.md
│   └── selection.json
├── large4m/...
├── slow/...
├── large8m/...                 # если выполнялся
├── selected-attempts.json
├── rc-benchmark.json
└── rc-benchmark.md
```

Ни один предыдущий attempt не удаляется. Это позволяет позже проверить, почему staircase была расширена.

## M15 evaluator

`perf/rc.py check` дополнительно к M12 проверяет:

- exact JSON boolean `strict_preflight=true`;
- `evidence_class=controlled`;
- минимум пять raw repeats;
- `manifest.repeats == decision.repeats == количество repeat-*`;
- exact scenario identity между manifest и каждым `capacity.json`;
- strict/valid raw host snapshots;
- единый host fingerprint;
- `first_failed_streams > max_sustainable_streams`;
- observed legacy/native boundary во всех repeats;
- `recommendation=native_preferred`;
- отсутствие `decision_reasons`.

Только после этого:

```text
ready = true
```

`perf/rc.py aggregate` дополнительно запрещает смешивать scenarios с разными:

- source commit;
- host fingerprint;
- NGINX version;
- compiler.

## Передача в M14

M14 ожидает один primary controlled directory. Для release evidence используется **selected typical attempt** из:

```text
selected-attempts.json
```

Runner также печатает его путь в конце.

После strict soak:

```bash
RELEASE_GATES=/data/rc/gates.json \
RELEASE_CONTROLLED_DIR=/data/nginx-grpc-web/rc-benchmark/typical/attempt-NN \
RELEASE_SOAK_DIR=/data/nginx-grpc-web/soak-8h \
NGINX_VERSION=1.30.4 \
BUILD_CC=gcc \
make release-check
```

Ожидаемый production результат M14:

```text
evidence_class = controlled
verdict = release_candidate
mechanics_pass = true
blockers = []
raw_revalidation.valid = true
```

M15 `rc-benchmark.json` с 4 MiB/slow/8 MiB является дополнительным архитектурным evidence и должен храниться рядом с M14 release bundle.

## Что M15 benchmark не делает

`make rc-benchmark` намеренно не:

- запускает 2h/8h soak автоматически;
- создаёт tag;
- создаёт GitHub Release;
- выполняет production rollout;
- меняет protocol scope;
- подставляет SLO thresholds за оператора.

Strict soak, staging acceptance и rollback остаются отдельными gates M15.
