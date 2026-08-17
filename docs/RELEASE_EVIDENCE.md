# Release candidate evidence

M14 вводит единый machine-checkable release evidence bundle для `v0.1.0`.

Цель — не добавить новый grpc-web функционал, а доказуемо связать один конкретный source commit с CI gates, собранным dynamic module, controlled-host performance evidence и soak evidence.

## Главный инвариант

Никакой copied/stale evidence не может быть повышен до release-candidate только потому, что внутри JSON написано `pass`.

`make release-check` независимо проверяет:

- текущий source commit и clean git tree;
- exact commit и evidence class обязательных `compatibility/protocol/differential/browser/hardening` gates;
- `source_commit`, NGINX version, compiler и `--with-compat` из package manifest;
- SHA256 `.so`, пересчитанный по реальному файлу, против `SHA256SUMS`;
- commit/NGINX/compiler controlled benchmark manifest;
- commit/NGINX/compiler soak manifest;
- evidence class M12/M13;
- строгий raw M12 host preflight (`strict=true`, `valid=true` как JSON booleans);
- совпадение controlled-host fingerprint между performance decision и soak;
- strict soak semantics;
- минимум 2 часа strict soak;
- M12 recommendation для native architecture;
- соответствие aggregate M11/M12/M13 JSON повторно вычисленным результатам из raw evidence.

Полный NGINX compatibility matrix из `docs/COMPATIBILITY.md` теперь представлен отдельным обязательным `compatibility` gate. Выбранный artifact/performance/soak target дополнительно сверяется по NGINX/compiler, поэтому успешный matrix gate нельзя смешать с evidence от другой сборки.

## Verdict model

M14 использует три основных состояния.

### `blocked`

Есть hard release blocker: checksum mismatch, stale commit, failed/missing test gate, несовместимый gate evidence class, dirty source tree, wrong build target, mixed host fingerprints, failed/short strict soak, несовпадение aggregate JSON с raw evidence, неверный JSON type и т.п.

Команда завершается ненулевым кодом.

### `inconclusive`

Механика evidence bundle корректна, но входные performance/soak данные имеют класс `harness_only`.

Это нормальный и ожидаемый результат shared GitHub Actions. Он **никогда** не является production-readiness claim.

По умолчанию `make release-check` возвращает non-zero и для `inconclusive`. Для ограниченного CI mechanics gate используется:

```bash
RELEASE_ALLOW_INCONCLUSIVE=1 make release-check
```

В этом режиме raw production revalidation намеренно не выполняется, а `revalidation.json` обязан явно содержать `skipped: harness_only`. Неявный skip считается ошибкой.

### `release_candidate`

Все machine-checkable M14 gates согласованы, каждый обязательный release gate имеет class `controlled`, controlled performance/soak evidence прошло policy, а aggregate performance/soak reports успешно пересчитаны из raw evidence.

Это означает только готовность evidence bundle к следующей стадии. `release_candidate` **не разрешает автоматически ставить tag или выкатывать production**. До `v0.1.0` остаются staging acceptance и ручное release/canary решение.

## Входные данные

### Gate evidence

`RELEASE_GATES` указывает на JSON с exact source commit и явным evidence class для каждого обязательного gate:

```json
{
  "compatibility": {
    "passed": true,
    "commit": "<exact-rc-sha>",
    "evidence_class": "controlled",
    "run_id": "..."
  },
  "protocol": {
    "passed": true,
    "commit": "<exact-rc-sha>",
    "evidence_class": "controlled",
    "run_id": "..."
  },
  "differential": {
    "passed": true,
    "commit": "<exact-rc-sha>",
    "evidence_class": "controlled",
    "run_id": "..."
  },
  "browser": {
    "passed": true,
    "commit": "<exact-rc-sha>",
    "evidence_class": "controlled",
    "run_id": "..."
  },
  "hardening": {
    "passed": true,
    "commit": "<exact-rc-sha>",
    "evidence_class": "controlled",
    "run_id": "..."
  }
}
```

`compatibility` означает завершённый release matrix из `docs/COMPATIBILITY.md`: stable/mainline NGINX и GCC/Clang build/load checks на exact release commit. `browser` агрегирует обязательную Chromium/Firefox/WebKit проверку.

Поле `passed` обязано быть настоящим JSON boolean. Строки `"true"`/`"false"`, числа и отсутствующее поле не приводятся к boolean и блокируют release. `evidence_class` обязан быть `controlled` либо `harness_only`; неизвестный или отсутствующий class блокирует bundle. Controlled `release_candidate` требует `controlled` для **каждого** обязательного gate. `harness_only` gate разрешён только в harness-only mechanics bundle и не может быть повышен до production evidence.

`run_id`/URL могут сохраняться для аудита, но release verdict опирается на `passed`, evidence class и exact commit linkage, а не на имя файла.

### Controlled benchmark

`RELEASE_CONTROLLED_DIR` должен указывать на **полный** output `perf/run-controlled.sh`, содержащий как минимум:

```text
manifest.json
slo.json
decision-policy.json
decision.json
decision.md
repeat-01/
  host.json
  report.json
  capacity.json
  ... raw load/resource results ...
repeat-02/...
```

Для production evidence ожидается:

- `manifest.json.git_commit == RC commit`;
- `manifest.json.strict_preflight` является JSON boolean `true`;
- выбранные NGINX/compiler совпадают с release target;
- scenario fields имеют ожидаемые JSON-типы;
- каждый raw `repeat-*/host.json` содержит **ровно** boolean `strict=true` и `valid=true`;
- каждый raw host имеет непустой fingerprint;
- `decision.json.evidence_class == controlled`;
- единый непустой host fingerprint;
- M12 decision не `inconclusive`.

Строки `"true"`/`"false"`, числа, `null` и отсутствующие `strict`/`valid` в raw M12 host snapshots считаются malformed evidence и блокируют production revalidation. Это проверяется до повторного запуска decision aggregation.

Raw repeat directories копируются в release bundle без потери provenance. Один `decision.json` без `report.json`, `capacity.json`, `host.json`, SLO и decision policy недостаточен для production release evidence.

### Soak

`RELEASE_SOAK_DIR` должен указывать на **полный** output `perf/run-soak.sh`:

```text
manifest.json
soak-policy.json
soak.json
soak.md
events.json
nginx.stats.tsv
cycle-*/...
```

Для controlled release evidence требуется:

- тот же source commit;
- тот же NGINX/compiler target;
- `strict` является JSON boolean `true`;
- strict host preflight содержит boolean `strict=true`, `valid=true`;
- тот же host fingerprint, что в M12 controlled decision;
- `evidence_class == controlled`;
- `verdict == soak_pass`;
- фактическая duration не меньше 7200 секунд.

Отдельный 8-hour run (`28800` секунд) остаётся рекомендуемым RC evidence и отмечается advisory `rc_soak_8h_recommended`, если bundle содержит только минимальный 2-hour run.

## Raw evidence revalidation

Production path (`RELEASE_ALLOW_INCONCLUSIVE=0`, default) не доверяет aggregate-файлам как конечному источнику истины.

Перед формированием final verdict `release/revalidate.py` выполняет:

1. требует `strict_preflight=true` в controlled manifest и exact JSON booleans `strict=true`, `valid=true` в каждом raw `repeat-*/host.json`;
2. для каждого `repeat-*` повторно запускает `perf/capacity.py` над сохранённым `report.json` с сохранёнными `slo.json` и scenario parameters из controlled manifest;
3. требует семантического равенства `capacity.revalidated.json` исходному `capacity.json`;
4. повторно запускает `perf/decision.py` над repeat-набором и сохранённым `decision-policy.json`;
5. требует семантического равенства `decision.revalidated.json` исходному `decision.json`;
6. повторно запускает `perf/soak.py --strict` над `nginx.stats.tsv`, `events.json` и `soak-policy.json`;
7. требует семантического равенства `soak.revalidated.json` исходному `soak.json`.

Результат сохраняется в:

```text
revalidation.json
```

Controlled `release_candidate` возможен только при:

```text
revalidation.valid = true
```

Если revalidation завершается ошибкой, `make release-check` всё равно сохраняет `revalidation.json`, строит final `release-evidence.json` со статусом `blocked/raw_revalidation` и только после этого возвращает ненулевой exit code. Это сохраняет причину отказа для аудита.

Это защищает от случайно устаревшего, вручную изменённого или неправильно перенесённого `decision.json`/`soak.json`, если raw evidence говорит другое.

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

Команда:

1. копирует raw controlled/soak evidence в release bundle;
2. повторно валидирует M11/M12/M13 aggregate reports из raw evidence;
3. заново собирает package artifact из текущего commit;
4. пересчитывает SHA256 `.so`;
5. проверяет cross-document provenance и обязательные exact-SHA/evidence-class gates;
6. создаёт `release-evidence.json` и `release-evidence.md`.

Нельзя подменить эти этапы простым копированием заранее опубликованного checksum или aggregate JSON.

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
  revalidation.json
  release-evidence.json
  release-evidence.md
  artifacts/
    nginx-1.30.4-gcc-linux-<arch>/
      ngx_http_grpc_web_module.so
      SHA256SUMS
      MANIFEST.txt
  controlled/
    manifest.json
    slo.json
    decision-policy.json
    decision.json
    decision.revalidated.json
    repeat-*/
      host.json
      report.json
      capacity.json
      capacity.revalidated.json
      ...
  soak/
    manifest.json
    soak-policy.json
    soak.json
    soak.revalidated.json
    events.json
    nginx.stats.tsv
    cycle-*/...
```

Controlled/soak trees копируются целиком: aggregate JSON без raw evidence недостаточен для long-term audit.

## Failure-closed behavior

M14 отвергает как минимум:

- checksum mismatch или malformed checksum digest;
- missing/duplicate checksum entry;
- malformed/duplicate package manifest fields;
- stale artifact source commit;
- dirty/unknown source tree state;
- missing/failed/stale compatibility/protocol/differential/browser/hardening gate;
- missing/unknown gate evidence class;
- `harness_only` gate при попытке сформировать controlled `release_candidate`;
- non-boolean gate/strict/preflight values;
- malformed raw M12 host strict/valid flags;
- stale controlled/soak commit;
- wrong NGINX/compiler identity;
- controlled decision `inconclusive` при попытке получить controlled RC;
- mixed performance/soak host fingerprints;
- non-strict controlled soak;
- failed strict host preflight;
- invalid/non-numeric soak duration;
- strict soak `< 7200 s`;
- missing raw repeat reports/SLO/decision policy/soak stats/events/policy;
- recomputed capacity/decision/soak, не совпадающие с сохранёнными aggregate reports;
- malformed/missing M12/M13 JSON.

Ошибки чтения/парсинга/типов превращаются в machine-readable `blocked` с reason `input_error` либо `raw_revalidation`, а не в implicit success.

## Shared CI

Workflow `.github/workflows/release-evidence.yml` намеренно использует synthetic exact-head M12/M13 fixtures только для проверки orchestration.

Он:

1. ограничивает `GITHUB_TOKEN` до `contents: read` и не сохраняет checkout credentials в рабочем дереве;
2. запускает failure-mode unit tests;
3. checkout'ит exact PR head, а не synthetic merge SHA;
4. генерирует `compatibility/protocol/differential/browser/hardening` gates с `evidence_class=harness_only`, привязанные к этому SHA;
5. генерирует `harness_only` M12/M13 reports;
6. явно фиксирует `revalidation.skipped = harness_only`;
7. реально собирает dynamic module через `scripts/package-module.sh`;
8. пересчитывает и проверяет checksum/manifest;
9. формирует полный release bundle;
10. требует итог:

```text
evidence_class = harness_only
verdict = inconclusive
mechanics_pass = true
gates.compatibility.passed = true
gates.compatibility.evidence_class = harness_only
raw_revalidation.skipped = harness_only
```

Synthetic compatibility gate в этом workflow проверяет **механику M14 aggregation**, а не заменяет реальный compatibility matrix. Production `gates.json` должен ссылаться на настоящий exact-release-commit CI result с `evidence_class=controlled`.

Любой `release_candidate` на shared CI для этого mechanics run является ошибкой release tooling.

## Что требуется перед tag `v0.1.0`

M14 сам tag не создаёт.

Перед ручным tag/release должны быть подтверждены:

1. exact RC commit находится в `main`;
2. post-merge compatibility/protocol/differential/browser/hardening CI green на exact release commit;
3. M14 artifact/evidence bundle согласован с этим commit;
4. controlled-host benchmark evidence сохранено вместе с raw repeat data;
5. strict soak минимум 2 часа сохранён вместе с raw stats/events;
6. `revalidation.json.valid == true`;
7. отдельный 8-hour RC soak выполнен или явно принято решение не выполнять рекомендацию;
8. staging acceptance из `docs/RELEASE_CHECKLIST.md` закрыт настоящим React client;
9. rollback на Envoy практически проверен;
10. только после этого вручную создаются tag `v0.1.0` и GitHub Release.

После tag начинается canary из `docs/ROLLOUT.md`; наличие release tag само по себе не является основанием удалить Envoy rollback pool.
