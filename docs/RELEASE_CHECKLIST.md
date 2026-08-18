# v0.1.0 release checklist

Этот checklist разделяет **готовность кода**, **machine-checkable release evidence**, **controlled/staging acceptance** и **production rollout**.

Наличие tooling не закрывает evidence gate автоматически. Checkbox отмечается только когда соответствующее evidence реально существует для exact release commit.

## POST-RELEASE VALIDATION (policy exception for v0.1.0)

Решение по этому релизу: `v0.1.0` тегируется и публикуется **без** ожидания controlled-host capacity benchmark, 2h/8h strict soak, real staging acceptance и practical Envoy rollback exercise. Эти проверки сознательно отложены, а не пропущены навсегда.

- functional/protocol/CI validation выполнена и является release-blocking (разделы 1–4, 7 частично);
- production-like performance/capacity/long-soak/staging validation **deferred**, controlled-host M15 evidence tooling смержено и провалидировано mechanics-only (unit/contract tests, CI smoke), но не выполнено на реальном dedicated host/staging;
- отложенные пункты остаются открытыми в GitHub Issue #20 и в `docs/POST_RELEASE_VALIDATION_v0.1.0.md`;
- CI/shared-runner numeric results (`evidence_class = harness_only`) не являются controlled evidence и не промоутируются в `controlled` для этого релиза;
- эта секция не отменяет разделы 5/6/8/9 ниже — она документирует, почему их checkbox остаётся open at tag time, и куда смотреть за прогрессом.

## 1. Source and scope

M15 tooling code baseline: `c22867c0d643dea069dd1bc605540dfe5f1c17be` (merge PR #21).

Release metadata была смержена после этой code baseline (PR #22 и последующие provenance-only release-prep изменения). **Авторитетный final release commit — commit, на который фактически указывает Git tag `v0.1.0`**. До публикации не следует фиксировать более ранний milestone SHA как tag target.

- [x] grpc-web v0.1 scope заморожен: unary binary/text + server streaming;
- [x] client streaming, bidi, grpc-web JSON остаются вне scope;
- [x] CORS/auth/routing/retries/service discovery не перенесены внутрь модуля;
- [x] M13 lifecycle/soak harness merged в `main`;
- [x] M14 находится в `main` (`4b7bc61468485f3d7266de0d81d614b2b8daaecd`, PR #17);
- [x] M15 tooling находится в `main` (`c22867c0d643dea069dd1bc605540dfe5f1c17be`, PR #21);
- [x] release metadata/provenance не выдают M15 milestone SHA за финальный tag target;

M15 controlled-host/staging **tooling** смержено; сами controlled/soak/staging *evidence* runs остаются deferred (см. POST-RELEASE VALIDATION).

## 2. Compatibility and code CI

M8–M13 доказали работоспособность test harness и текущего protocol contract; перед tag требуется **post-merge run на exact commit, который станет tag target**.

Поддерживаемый v0.1 matrix:

- NGINX stable `1.30.4`;
- NGINX mainline `1.31.3`;
- GCC + Clang build/load checks;
- Chromium + Firefox + WebKit browser runtime.

Release gates:

- [x] stable 1.30.4 + GCC build/load green;
- [x] stable 1.30.4 + Clang build/load green;
- [x] mainline 1.31.3 + GCC build/load green;
- [x] mainline 1.31.3 + Clang build/load green;
- [x] protocol suite green (`integration` 1.30.4/1.31.3);
- [x] Envoy differential suite green (`integration`);
- [x] Chromium real React/`grpc-web` suite green;
- [x] Firefox real React/`grpc-web` suite green;
- [x] WebKit real React/`grpc-web` suite green;
- [x] ASAN/UBSAN green (`hardening`);
- [x] Base64/frame fuzz smoke green (`hardening`);
- [x] media-type/malformed-frame/transport-reset/logging hardening green.

Validated post-merge baselines:

- M15 merge `c22867c0d643dea069dd1bc605540dfe5f1c17be`: CI run `32039399834`, `success`;
- release-metadata merge `4b20419b317fae9ce1432f03a0e62359654abaaa`: CI run `32040470473`, `success`.

После merge этого provenance-fix PR final tag target должен получить собственный green post-merge CI; именно этот resulting `main` SHA допускается тегировать.

## 3. M14 release evidence tooling

Tooling считается реализованным только после merge M14, но production evidence появляется только после controlled/staging выполнения.

- [x] deterministic pure release evaluator реализован;
- [x] failure-mode tests включают checksum, stale SHA, host mismatch, short soak и `harness_only` promotion;
- [x] collector пересчитывает artifact SHA256 и читает package/M12/M13 provenance;
- [x] production path повторно вычисляет M11 capacity, M12 decision и M13 soak из raw evidence;
- [x] final verdict требует `raw_revalidation.valid == true` для controlled evidence;
- [x] `make release-check` формирует self-contained evidence bundle;
- [x] shared-CI design требует `harness_only/inconclusive` и явный `revalidation.skipped=harness_only`;
- [x] exact M14 PR head release-evidence workflow green (PR #17);
- [x] M14 merged в `main`;
- [x] M15 tooling mechanics merged и CI validated.

Подробности: `docs/RELEASE_EVIDENCE.md`.

## 4. Binary artifact

Production release не публикует generic `.so` для всех NGINX packages.

Для выбранного artifact target:

```bash
NGINX_VERSION=1.30.4 BUILD_CC=gcc make package-module
```

или в составе полного evidence command:

```bash
RELEASE_GATES=/data/rc/gates.json \
RELEASE_CONTROLLED_DIR=/data/rc/controlled \
RELEASE_SOAK_DIR=/data/rc/soak \
make release-check
```

Проверки перед публикацией:

- [ ] `.so` заново собран из exact tag-target commit;
- [ ] `MANIFEST.txt.source_commit` совпадает с tag-target commit;
- [ ] NGINX/compiler/platform/build mode зафиксированы;
- [ ] SHA256 пересчитан по реальному `.so` и совпадает с `SHA256SUMS`;
- [ ] artifact сохранён для загрузки в GitHub Release;
- [ ] compatibility disclaimer для distro/vendor NGINX сохранён.

## 5. Controlled-host performance evidence — DEFERRED for v0.1.0 (see POST-RELEASE VALIDATION, Issue #20)

Shared GitHub runner не закрывает этот раздел.

Требуется M12 strict controlled run на одной стабильной машине с непересекающимися CPU sets gateway/backend/loadgen.

- [ ] host preflight `strict=true`, `valid=true`;
- [ ] host fingerprint сохранён;
- [ ] минимум policy-defined repeat count выполнен;
- [ ] full TLS/H2 capacity staircases сохранены;
- [ ] `slo.json` и `decision-policy.json` сохранены вместе с результатами;
- [ ] каждый `repeat-*` содержит `host.json`, raw `report.json` и `capacity.json`;
- [ ] repeat variance укладывается в policy;
- [ ] `decision.json.evidence_class == controlled`;
- [ ] architecture decision не `inconclusive`;
- [ ] controlled manifest source commit совпадает с release commit;
- [ ] raw repeat artifacts сохранены в release bundle;
- [ ] повторно вычисленные `capacity.revalidated.json` совпадают с исходными `capacity.json`;
- [ ] повторно вычисленный `decision.revalidated.json` совпадает с исходным `decision.json`.

## 6. Strict soak evidence — DEFERRED for v0.1.0 (see POST-RELEASE VALIDATION, Issue #20)

Shared `perf-soak-smoke` проверяет orchestration и **не закрывает этот раздел**.

### Mandatory 2-hour gate

- [ ] soak strict host preflight valid;
- [ ] source commit совпадает с release commit;
- [ ] host fingerprint совпадает с M12 controlled decision;
- [ ] duration `>= 7200 s`;
- [ ] `soak-policy.json`, `events.json` и `nginx.stats.tsv` сохранены;
- [ ] RSS slope/growth policy green;
- [ ] steady/churn/cancel accounting green;
- [ ] hard backend disruption наблюдался и recovery green;
- [ ] transport resets accounted и recovery green;
- [ ] final healthy probe green;
- [ ] NGINX master/container не перезапускались;
- [ ] `soak.json.evidence_class == controlled`;
- [ ] `soak.json.verdict == soak_pass`;
- [ ] raw samples/events/cycles сохранены;
- [ ] повторно вычисленный `soak.revalidated.json` совпадает с исходным `soak.json`.

### Recommended 8-hour RC soak

- [ ] отдельный `SOAK_DURATION_SECONDS=28800` RC run выполнен;
- [ ] 8h artifact сохранён рядом с release evidence;
- [ ] если 8h recommendation сознательно пропущена, решение и rationale зафиксированы вручную.

## 7. Final M14 bundle — controlled/soak inputs DEFERRED for v0.1.0 (see POST-RELEASE VALIDATION, Issue #20)

This bundle requires the section 5/6/8 evidence above; it cannot be produced until that evidence exists, so it is deferred alongside them for this release.

Ожидаемый bundle:

```text
dist/release/v0.1.0-rc/
  gates.json
  revalidation.json
  release-evidence.json
  release-evidence.md
  artifacts/...
  controlled/...
  soak/...
```

- [ ] `make release-check` завершился успешно без `RELEASE_ALLOW_INCONCLUSIVE=1`;
- [ ] `revalidation.json.valid == true`;
- [ ] `release-evidence.json.raw_revalidation.valid == true`;
- [ ] `evidence_class == controlled`;
- [ ] `verdict == release_candidate`;
- [ ] blockers пусты;
- [ ] bundle сохранён в постоянном release storage;
- [ ] bundle вручную просмотрен на provenance consistency.

`release_candidate` — это machine-checkable M14 state, а не разрешение автоматически ставить tag.

## 8. Staging acceptance — DEFERRED for v0.1.0 (see POST-RELEASE VALIDATION, Issue #20)

Artifact устанавливается тем же способом, который будет использовать production.

- [ ] `nginx -t` green;
- [ ] effective `nginx -T` сохранён;
- [ ] настоящий React client: unary binary green;
- [ ] настоящий React client: grpc-web-text unary green;
- [ ] настоящий React client: server streaming incremental green;
- [ ] non-zero `grpc-status` / `grpc-message` green;
- [ ] client cancellation propagation green;
- [ ] deadline / `grpc-timeout` green;
- [ ] upstream unavailable normalization green;
- [ ] proxy timeout normalization green;
- [ ] long stream RSS observation acceptable;
- [ ] rollback с native NGINX path обратно на Envoy практически проверен.

## 9. Tag and GitHub Release

Policy exception for `v0.1.0`: тег создаётся после закрытия source/CI/artifact/package gates, **без** ожидания controlled/soak/staging/rollback (разделы 5/6/8), которые сознательно deferred в Issue #20.

- [x] M14/M15 code/tooling merged в `main`;
- [x] exact final tag-target commit находится в `main` и имеет green post-merge CI (`2bb375437a46c59e0a099a56aa69a8be332721a8`, `ci` run `32072809635`);
- [ ] final controlled M14 bundle — deferred (Issue #20);
- [ ] staging acceptance — deferred (Issue #20);
- [x] tag `v0.1.0` вручную указывает на exact final tag-target commit (published by `publish-v0.1.0` workflow run `32072968401`);
- [x] GitHub Release создан из `docs/RELEASE_NOTES_v0.1.0.md`: https://github.com/mnevrov/nginx-grpc-web/releases/tag/v0.1.0;
- [x] published artifact checksums приложены к release (`SHA256SUMS`, verified locally against the downloaded `.so`);
- [x] final CI/tag references проверены перед публикацией.

## 10. Production rollout

Следовать `docs/ROLLOUT.md`.

- [ ] production baseline captured;
- [ ] 1% canary;
- [ ] 5–10%;
- [ ] 25–50%;
- [ ] 100%;
- [ ] Envoy rollback pool остаётся warm на agreed observation window;
- [ ] errors/latency/RSS сравниваются с baseline на каждом этапе;
- [ ] rollback criteria операционно понятны и проверены;
- [ ] удаление Envoy оформлено отдельным change после стабильного observation window.

## 11. Post-release maintenance

- [ ] compatibility matrix зафиксирована датой release;
- [ ] security updates NGINX отслеживаются с приоритетом;
- [ ] новый stable/mainline NGINX добавляется отдельным compatibility PR;
- [ ] published release evidence остаётся доступным для аудита;
- [ ] никакой последующий artifact не переиспользует `v0.1.0` checksum после изменения source/build environment.
