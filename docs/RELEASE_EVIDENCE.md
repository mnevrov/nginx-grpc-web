# Release candidate evidence

M14 вводит единый machine-checkable release evidence bundle для `v0.1.0`.

Цель — не добавить новый grpc-web функционал, а доказуемо связать один конкретный source commit с CI gates, собранным dynamic module, controlled-host performance evidence и soak evidence.

## Главный инвариант

Никакой copied/stale evidence не может быть повышен до release-candidate только потому, что внутри JSON написано `pass`.

`make release-check` независимо проверяет:

- текущий source commit и clean git tree;
- commit каждого protocol/differential/browser/hardening gate;
- `source_commit`, NGINX version, compiler и `--with-compat` из package manifest;
- SHA256 `.so`, пересчитанный по реальному файлу, против `SHA256SUMS`;
- commit/NGINX/compiler controlled benchmark manifest;
- commit/NGINX/compiler soak manifest;
- evidence class M12/M13;
- совпадение controlled-host fingerprint между performance decision и soak;
- strict soak semantics;
- минимум 2 часа strict soak;
- M12 recommendation для native architecture.

Full NGINX compatibility matrix остаётся отдельным source/CI release gate из `docs/COMPATIBILITY.md`. M14 дополнительно запрещает смешивать artifact/performance/soak от другого выбранного NGINX/compiler target.

## Verdict model

M14 использует три основных состояния.

### `blocked`

Есть hard release blocker: checksum mismatch, stale commit, failed/missing test gate, dirty source tree, wrong build target, mixed host fingerprints, failed/short strict soak и т.п.

Команда завершается ненулевым кодом.

### `inconclusive`

Механика evidence bundle корректна, но входные performance/soak данные имеют класс `harness_only`.

Это нормальный и ожидаемый результат shared GitHub Actions. Он **никогда** не является production-readiness claim.

По умолчанию `make release-check` возвращает non-zero и для `inconclusive`. Для ограниченного CI mechanics gate используется:

```bash
RELEASE_ALLOW_INCONCLUSIVE=1 make release-check
```

### `release_candidate`

Все machine-checkable M14 gates согласованы и controlled evidence прошло policy.

Это означает только готовность evidence bundle к следующей стадии. `release_candidate` **не разрешает автоматически ставить tag или выкатывать production**. До `v0.1.0` остаются staging acceptance и ручное release/canary решение.

## Входные данные

### Gate evidence

`RELEASE_GATES` указывает на JSON с exact source commit для каждого gate:

```json
{
  "protocol": {
    "passed": true,
    "commit": "<exact-rc-sha>",
    "run_id": "..."
  },
  "differential": {
    "passed": true,
    "commit": "<exact-rc-sha>",
    "run_id": "..."
  },
  "browser": {
    "passed": true,
    "commit": "<exact-rc-sha>",
    "run_id": "..."
  },
  "hardening": {
    "passed": true,
    "commit": "<exact-rc-sha>",
    "run_id": "..."
  }
}
```

`run_id`/URL могут сохраняться для аудита, но release verdict опирается на `passed` и exact commit linkage, а не на имя файла.

### Controlled benchmark

`RELEASE_CONTROLLED_DIR` должен указывать на полный output `perf/run-controlled.sh`, содержащий как минимум:

```text
manifest.json
decision.json
decision.md
repeat-*/...
```

Для production evidence ожидается:

- `manifest.json.git_commit == RC commit`;
- выбранные NGINX/compiler совпадают с release target;
- `decision.json.evidence_class == controlled`;
- единый непустой host fingerprint;
- M12 decision не `inconclusive`.

Raw repeat directories копируются в release bundle без потери provenance.

### Soak

`RELEASE_SOAK_DIR` должен указывать на полный output `perf/run-soak.sh`:

```text
manifest.json
soak.json
soak.md
events.json
nginx.stats.tsv
cycle-*/...
```

Для controlled release evidence требуется:

- тот же source commit;
- тот же NGINX/compiler target;
- strict host preflight;
- тот же host fingerprint, что в M12 controlled decision;
- `evidence_class == controlled`;
- `verdict == soak_pass`;
- фактическая duration не меньше 7200 секунд.

Отдельный 8-hour run (`28800` секунд) остаётся рекомендуемым RC evidence и отмечается advisory `rc_soak_8h_recommended`, если bundle содержит только минимальный 2-hour run.

## Запуск

Типовой controlled запуск после получения всех входов:

```bash
RELEASE_GATES=/data/rc/gates.json \
RELEASE_CONTROLLED_DIR=/data/rc/controlled \
RELEASE_SOAK_DIR=/data/rc/soak-8h \
NGINX_VERSION=1.30.4 \
BUILD_CC=gcc \
make release-check
```

Команда сама заново собирает package artifact. Нельзя подменить этот этап простым копированием заранее опубликованного checksum.

По умолчанию результат создаётся в:

```text
dist/release/v0.1.0-rc/
```

Другой output directory:

```bash
RELEASE_OUTPUT_DIR=/data/evidence/v0.1.0-rc make release-check
```

## Bundle layout

```text
dist/release/v0.1.0-rc/
  gates.json
  release-evidence.json
  release-evidence.md
  artifacts/
    nginx-1.30.4-gcc-linux-<arch>/
      ngx_http_grpc_web_module.so
      SHA256SUMS
      MANIFEST.txt
  controlled/
    manifest.json
    decision.json
    decision.md
    repeat-*/...
  soak/
    manifest.json
    soak.json
    soak.md
    events.json
    nginx.stats.tsv
    cycle-*/...
```

Controlled/soak trees копируются целиком: aggregate JSON без raw evidence недостаточен для long-term audit.

## Failure-closed behavior

M14 отвергает как минимум:

- checksum mismatch;
- missing/duplicate checksum entry;
- malformed package manifest;
- stale artifact source commit;
- dirty source tree;
- missing/failed/stale protocol/browser/hardening gate;
- stale controlled/soak commit;
- wrong NGINX/compiler identity;
- controlled decision `inconclusive` при попытке получить controlled RC;
- mixed performance/soak host fingerprints;
- non-strict controlled soak;
- failed strict host preflight;
- strict soak `< 7200 s`;
- malformed/missing M12/M13 JSON.

Ошибки чтения/парсинга превращаются в machine-readable `blocked` с reason `input_error`, а не в implicit success.

## Shared CI

Workflow `.github/workflows/release-evidence.yml` намеренно использует synthetic exact-head M12/M13 fixtures только для проверки orchestration.

Он:

1. запускает failure-mode unit tests;
2. checkout'ит exact PR head, а не synthetic merge SHA;
3. генерирует `harness_only` reports, привязанные к этому SHA;
4. реально собирает dynamic module через `scripts/package-module.sh`;
5. пересчитывает и проверяет checksum/manifest;
6. формирует полный release bundle;
7. требует итог:

```text
evidence_class = harness_only
verdict = inconclusive
mechanics_pass = true
```

Любой `release_candidate` на shared CI для этого mechanics run является ошибкой release tooling.

## Что требуется перед tag `v0.1.0`

M14 сам tag не создаёт.

Перед ручным tag/release должны быть подтверждены:

1. exact RC commit находится в `main`;
2. post-merge compatibility/protocol/differential/browser/hardening CI green на exact release commit;
3. M14 artifact/evidence bundle согласован с этим commit;
4. controlled-host benchmark evidence сохранено;
5. strict soak минимум 2 часа сохранён;
6. отдельный 8-hour RC soak выполнен или явно принято решение не выполнять рекомендацию;
7. staging acceptance из `docs/RELEASE_CHECKLIST.md` закрыт настоящим React client;
8. rollback на Envoy практически проверен;
9. только после этого вручную создаются tag `v0.1.0` и GitHub Release.

После tag начинается canary из `docs/ROLLOUT.md`; наличие release tag само по себе не является основанием удалить Envoy rollback pool.
