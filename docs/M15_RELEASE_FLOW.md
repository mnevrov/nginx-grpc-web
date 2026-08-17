# M15 — End-to-end RC evidence flow

Этот документ задаёт **единственный рекомендуемый порядок** получения evidence перед ручным `v0.1.0` release.

M15 не создаёт tag, GitHub Release и не выполняет production rollout автоматически.

## 0. Подготовка exact source

Работайте на clean worktree exact RC commit:

```bash
git status --short
git rev-parse HEAD
```

Все benchmark, soak, M14 release bundle и staging evidence должны ссылаться на один и тот же commit.

## 1. Controlled RC benchmark

На выделенном controlled host:

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

Если 8 MiB scenario объективно невозможно выполнить на target-class host, вместо `RC_LARGE8M_SLO` должен быть задан явный `RC_SKIP_LARGE8M_REASON`.

Успех означает:

```text
rc-benchmark.json.ready = true
blockers = []
all selected scenarios = controlled/native_preferred
real legacy/native SLO boundary observed in all selected repeats
```

Подробности: `docs/RC_BENCHMARK.md`.

## 2. Strict soak на том же host fingerprint

Минимальный release gate:

```bash
RC_BENCHMARK_DIR=/data/nginx-grpc-web/rc-benchmark \
RC_SOAK_DURATION_SECONDS=7200 \
RC_SOAK_OUTPUT_DIR=/data/nginx-grpc-web/soak-2h \
make rc-soak
```

Рекомендуемый RC gate:

```bash
RC_BENCHMARK_DIR=/data/nginx-grpc-web/rc-benchmark \
RC_SOAK_DURATION_SECONDS=28800 \
RC_SOAK_OUTPUT_DIR=/data/nginx-grpc-web/soak-8h \
make rc-soak
```

Wrapper **до запуска** длинного теста проверяет, что текущий source SHA и strict host fingerprint совпадают с benchmark. После запуска проверяются M13 lifecycle semantics и фактическая duration.

Если для release используется только 2h soak, финальный M15 gate потребует отдельный non-empty waiver/decision record.

## 3. Сформировать controlled M14 release bundle

Подготовьте `gates.json` на exact commit. Все обязательные M14 gates должны быть `controlled`:

```text
compatibility
protocol
differential
browser
hardening
```

Затем:

```bash
RC_BENCHMARK_DIR=/data/nginx-grpc-web/rc-benchmark \
RC_SOAK_DIR=/data/nginx-grpc-web/soak-8h \
RELEASE_GATES=/data/nginx-grpc-web/gates.json \
RC_RELEASE_OUTPUT_DIR=/data/nginx-grpc-web/v0.1.0-rc \
make rc-release-check
```

Команда сама выбирает `typical` attempt, выбранный M15 evaluator’ом, и передаёт его в M14 `release-check`.

Она требует итог:

```text
release-evidence.json.evidence_class = controlled
release-evidence.json.verdict = release_candidate
release-evidence.json.mechanics_pass = true
release-evidence.json.blockers = []
release-evidence.json.raw_revalidation.valid = true
```

M14 при этом **заново собирает dynamic module** из exact source commit и помещает package в:

```text
/data/nginx-grpc-web/v0.1.0-rc/artifacts/
```

## 4. Установить в staging именно artifact из M14 bundle

Не используйте старый `.so` из другого CI artifact или локальной сборки.

Установите package из шага 3 способом, идентичным production deployment.

Сохраните:

```text
nginx -V
nginx -T
sha256sum deployed ngx_http_grpc_web_module.so
RSS/worker/restart observation
```

Deployed SHA должен совпадать с `release-evidence.json.artifact.sha256`.

## 5. Native staging React acceptance

```bash
STAGING_ENDPOINT=https://staging.example/grpc-web \
STAGING_UNAVAILABLE_ENDPOINT=https://staging.example/grpc-web-unavailable \
STAGING_TIMEOUT_ENDPOINT=https://staging.example/grpc-web-timeout \
STAGING_LABEL=native-module \
STAGING_OUTPUT_DIR=/data/nginx-grpc-web/staging/native/browser \
make staging-browser
```

Используется тот же React/`grpc-web` client, что в обычной browser matrix.

## 6. Практический rollback на Envoy

Реально переключите staging traffic на Envoy через production-like rollout layer. Внешние endpoint URL для клиента должны остаться теми же.

Сохраните routing-change evidence и повторите тот же browser suite:

```bash
STAGING_ENDPOINT=https://staging.example/grpc-web \
STAGING_UNAVAILABLE_ENDPOINT=https://staging.example/grpc-web-unavailable \
STAGING_TIMEOUT_ENDPOINT=https://staging.example/grpc-web-timeout \
STAGING_LABEL=envoy-rollback \
STAGING_OUTPUT_DIR=/data/nginx-grpc-web/staging/envoy-rollback/browser \
make staging-browser
```

Подробности: `docs/STAGING_ACCEPTANCE.md`.

## 7. Сформировать staging evidence

```bash
STAGING_PACKAGE_DIR=/data/nginx-grpc-web/v0.1.0-rc/artifacts/nginx-1.30.4-gcc-linux-x86_64 \
STAGING_NATIVE_BROWSER_DIR=/data/nginx-grpc-web/staging/native/browser \
STAGING_ROLLBACK_BROWSER_DIR=/data/nginx-grpc-web/staging/envoy-rollback/browser \
STAGING_NGINX_V=/data/nginx-grpc-web/staging/native/nginx-V.txt \
STAGING_NGINX_T=/data/nginx-grpc-web/staging/native/nginx-T.txt \
STAGING_DEPLOYED_SHA256=/data/nginx-grpc-web/staging/native/deployed-module.sha256 \
STAGING_RSS_EVIDENCE=/data/nginx-grpc-web/staging/native/rss-observation.txt \
STAGING_ROLLBACK_EVIDENCE=/data/nginx-grpc-web/staging/envoy-rollback/routing-change.txt \
STAGING_EVIDENCE_OUTPUT_DIR=/data/nginx-grpc-web/staging/evidence \
make staging-evidence
```

Ожидаемый итог:

```text
staging-evidence.json.verdict = staging_pass
```

Validator связывает package SHA, deployed SHA, source commit, `nginx -V/-T`, native React run и rollback React run. Native и rollback browser manifests обязаны содержать одинаковые внешние endpoints.

## 8. Финальный M15 check

### Вариант A: 8h soak выполнен

```bash
RC_BENCHMARK_DIR=/data/nginx-grpc-web/rc-benchmark \
RC_SOAK_DIR=/data/nginx-grpc-web/soak-8h \
RC_RELEASE_DIR=/data/nginx-grpc-web/v0.1.0-rc \
STAGING_EVIDENCE_FILE=/data/nginx-grpc-web/staging/evidence/staging-evidence.json \
M15_OUTPUT_DIR=/data/nginx-grpc-web/v0.1.0-rc/m15-final \
make m15-check
```

### Вариант B: только обязательный 2h soak

Создайте отдельный decision record, например:

```text
/data/nginx-grpc-web/8h-soak-waiver.txt
```

Он должен объяснять, кто/почему принял решение продолжить release без рекомендуемого 8h run.

```bash
RC_BENCHMARK_DIR=/data/nginx-grpc-web/rc-benchmark \
RC_SOAK_DIR=/data/nginx-grpc-web/soak-2h \
RC_RELEASE_DIR=/data/nginx-grpc-web/v0.1.0-rc \
STAGING_EVIDENCE_FILE=/data/nginx-grpc-web/staging/evidence/staging-evidence.json \
RC_8H_WAIVER=/data/nginx-grpc-web/8h-soak-waiver.txt \
M15_OUTPUT_DIR=/data/nginx-grpc-web/v0.1.0-rc/m15-final \
make m15-check
```

Ожидаемый итог:

```text
m15-evidence.json.ready = true
m15-evidence.json.verdict = ready_for_manual_release
blockers = []
```

При 2h waiver дополнительно будет advisory:

```text
eight_hour_soak_waived
```

## 9. Только ручное release decision

`ready_for_manual_release` **не создаёт release автоматически**.

После него вручную выполняются:

1. финальная проверка evidence;
2. tag `v0.1.0` на exact approved commit;
3. GitHub Release с package/checksums/release notes;
4. production canary `1% -> 5–10% -> 25–50% -> 100%`;
5. Envoy остаётся warm rollback path на observation window;
6. удаление Envoy — отдельное изменение после успешного наблюдения.

## Fail-closed guarantees

Flow остановится при любом из случаев:

- stale/mixed source commit;
- mixed host fingerprints;
- insufficient controlled repeats;
- capacity boundary не достигнута;
- M12 decision не `native_preferred`;
- short soak <2h;
- 2h run без 8h waiver;
- harness-only M14 evidence;
- M14 raw revalidation не прошла;
- staging package SHA != release package SHA;
- native staging browser failure;
- rollback browser failure;
- rollback изменил внешний endpoint клиента;
- missing `nginx -V/-T`, RSS или routing-change evidence;
- 8 MiB scenario neither run nor explicitly waived by hardware rationale.
