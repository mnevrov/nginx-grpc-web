# v0.1.0 release checklist

Этот checklist разделяет **готовность кода**, **machine-checkable release evidence**, **controlled/staging acceptance** и **production rollout**.

Наличие tooling не закрывает evidence gate автоматически. Checkbox отмечается только когда соответствующее evidence реально существует для exact release commit.

## 1. Source and scope

Текущая M13 production-code baseline: `249cf1d013fc04db8cebd54ae4e061b879c1f381` в `main`.

- [x] grpc-web v0.1 scope заморожен: unary binary/text + server streaming;
- [x] client streaming, bidi, grpc-web JSON остаются вне scope;
- [x] CORS/auth/routing/retries/service discovery не перенесены внутрь модуля;
- [x] M13 lifecycle/soak harness merged в `main`;
- [ ] финальный release commit M14 находится в `main`;
- [ ] release source tree clean;
- [ ] release notes/changelog указывают на финальный release commit, а не более раннюю baseline.

## 2. Compatibility and code CI

M8–M13 уже доказали работоспособность test harness и текущего protocol contract, но перед tag требуется **post-merge run на exact release commit**.

Поддерживаемый v0.1 matrix:

- NGINX stable `1.30.4`;
- NGINX mainline `1.31.3`;
- GCC + Clang build/load checks;
- Chromium + Firefox + WebKit browser runtime.

Release gates:

- [ ] stable 1.30.4 + GCC build/load green на exact release commit;
- [ ] stable 1.30.4 + Clang build/load green на exact release commit;
- [ ] mainline 1.31.3 + GCC build/load green на exact release commit;
- [ ] mainline 1.31.3 + Clang build/load green на exact release commit;
- [ ] protocol suite green;
- [ ] Envoy differential suite green;
- [ ] Chromium real React/`grpc-web` suite green;
- [ ] Firefox real React/`grpc-web` suite green;
- [ ] WebKit real React/`grpc-web` suite green;
- [ ] ASAN/UBSAN green;
- [ ] Base64/frame fuzz smoke green;
- [ ] media-type/malformed-frame/transport-reset/logging hardening green.

IDs/URLs exact release CI runs должны быть сохранены в release evidence/release notes.

## 3. M14 release evidence tooling

Tooling считается реализованным только после merge M14, но production evidence появляется только после controlled/staging выполнения.

- [x] deterministic pure release evaluator реализован в M14 branch;
- [x] failure-mode tests включают checksum, stale SHA, host mismatch, short soak и `harness_only` promotion;
- [x] collector пересчитывает artifact SHA256 и читает package/M12/M13 provenance;
- [x] `make release-check` формирует self-contained evidence bundle;
- [x] shared-CI design требует `harness_only/inconclusive`;
- [ ] exact M14 PR head release-evidence workflow green;
- [ ] M14 merged в `main`;
- [ ] post-merge release-evidence mechanics run green.

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

Проверки:

- [ ] `.so` заново собран из exact release commit;
- [ ] `MANIFEST.txt.source_commit` совпадает с release commit;
- [ ] NGINX/compiler/platform/build mode зафиксированы;
- [ ] SHA256 пересчитан по реальному `.so` и совпадает с `SHA256SUMS`;
- [ ] artifact сохранён вместе с release evidence bundle;
- [ ] compatibility disclaimer для distro/vendor NGINX сохранён.

## 5. Controlled-host performance evidence

Shared GitHub runner не закрывает этот раздел.

Требуется M12 strict controlled run на одной стабильной машине с непересекающимися CPU sets gateway/backend/loadgen.

- [ ] host preflight `strict=true`, `valid=true`;
- [ ] host fingerprint сохранён;
- [ ] минимум policy-defined repeat count выполнен;
- [ ] full TLS/H2 capacity staircases сохранены;
- [ ] repeat variance укладывается в policy;
- [ ] `decision.json.evidence_class == controlled`;
- [ ] architecture decision не `inconclusive`;
- [ ] controlled manifest source commit совпадает с release commit;
- [ ] raw repeat artifacts сохранены в release bundle.

## 6. Strict soak evidence

Shared `perf-soak-smoke` проверяет orchestration и **не закрывает этот раздел**.

### Mandatory 2-hour gate

- [ ] soak strict host preflight valid;
- [ ] source commit совпадает с release commit;
- [ ] host fingerprint совпадает с M12 controlled decision;
- [ ] duration `>= 7200 s`;
- [ ] RSS slope/growth policy green;
- [ ] steady/churn/cancel accounting green;
- [ ] hard backend disruption наблюдался и recovery green;
- [ ] transport resets accounted и recovery green;
- [ ] final healthy probe green;
- [ ] NGINX master/container не перезапускались;
- [ ] `soak.json.evidence_class == controlled`;
- [ ] `soak.json.verdict == soak_pass`;
- [ ] raw samples/events/cycles сохранены.

### Recommended 8-hour RC soak

- [ ] отдельный `SOAK_DURATION_SECONDS=28800` RC run выполнен;
- [ ] 8h artifact сохранён рядом с release evidence;
- [ ] если 8h recommendation сознательно пропущена, решение и rationale зафиксированы вручную.

## 7. Final M14 bundle

Ожидаемый bundle:

```text
dist/release/v0.1.0-rc/
  gates.json
  release-evidence.json
  release-evidence.md
  artifacts/...
  controlled/...
  soak/...
```

- [ ] `make release-check` завершился успешно без `RELEASE_ALLOW_INCONCLUSIVE=1`;
- [ ] `evidence_class == controlled`;
- [ ] `verdict == release_candidate`;
- [ ] blockers пусты;
- [ ] bundle сохранён в постоянном release storage;
- [ ] bundle вручную просмотрен на provenance consistency.

`release_candidate` — это machine-checkable M14 state, а не разрешение автоматически ставить tag.

## 8. Staging acceptance

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

До закрытия source/CI/artifact/controlled/soak/staging gates tag не создаётся.

- [ ] финальный release commit находится в `main`;
- [ ] post-merge exact-commit CI green;
- [ ] final controlled M14 bundle сохранён;
- [ ] staging acceptance закрыт;
- [ ] tag `v0.1.0` вручную указывает на exact release commit;
- [ ] GitHub Release создан из `docs/RELEASE_NOTES_v0.1.0.md`;
- [ ] published artifact checksums записаны в release notes;
- [ ] final CI/evidence references записаны в release notes.

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
