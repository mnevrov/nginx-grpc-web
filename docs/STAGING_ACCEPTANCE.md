# M15 — Staging acceptance & Envoy rollback

M15 staging проверяет **реальный React/`grpc-web` клиент** против установленного staging-модуля. Это не отдельный curl-клиент и не NGINX-specific frontend workaround: используется тот же `tests/browser/src/client.mjs`, который применялся в M2–M14.

## Предусловия

Перед staging acceptance должны быть известны:

- exact Git commit;
- пакет `.so`, собранный из этого commit;
- `SHA256SUMS` и `MANIFEST.txt` пакета;
- способ установки, идентичный production deployment;
- native staging endpoint;
- staging fault endpoint для upstream unavailable;
- staging fault endpoint для proxy timeout;
- рабочий Envoy rollback route/pool.

Fault endpoints являются **staging configuration**, а не функциональностью модуля. Нельзя добавлять production route/fault behavior внутрь `ngx_http_grpc_web_module` ради прохождения этого теста.

## Что автоматизировано

Отдельный Playwright suite:

```text
tests/browser/playwright.staging.config.ts
tests/browser/staging/staging.spec.ts
```

проверяет:

1. binary unary;
2. grpc-web-text unary;
3. server streaming: первое DATA приходит, пока RPC ещё `running`;
4. полный sequence server stream;
5. non-zero `grpc-status`/`grpc-message`;
6. browser cancellation;
7. `grpc-timeout` → `DEADLINE_EXCEEDED (4)`;
8. local unavailable normalization → `UNAVAILABLE (14)`;
9. local proxy timeout normalization → `DEADLINE_EXCEEDED (4)`;
10. более длинный stream без browser-side buffering/corruption.

Suite работает с произвольным endpoint через уже существующий `?endpoint=` browser harness.

## Первый run — native module

Установите пакет в staging и сохраните deployment evidence до запуска browser suite.

Рекомендуемый каталог:

```text
/data/nginx-grpc-web/staging/native/
```

Сохраните как минимум:

```bash
nginx -V 2>&1 > /data/nginx-grpc-web/staging/native/nginx-V.txt
nginx -T 2>&1 > /data/nginx-grpc-web/staging/native/nginx-T.txt
sha256sum /path/to/ngx_http_grpc_web_module.so \
  > /data/nginx-grpc-web/staging/native/deployed-module.sha256
```

Checksum deployed `.so` должен совпадать с пакетом exact release commit.

Затем:

```bash
STAGING_ENDPOINT=https://staging.example/grpc-web \
STAGING_UNAVAILABLE_ENDPOINT=https://staging.example/grpc-web-unavailable \
STAGING_TIMEOUT_ENDPOINT=https://staging.example/grpc-web-timeout \
STAGING_BROWSER=chromium \
STAGING_LABEL=native-module \
STAGING_OUTPUT_DIR=/data/nginx-grpc-web/staging/native/browser \
./scripts/run-staging-browser.sh
```

Wrapper:

- требует clean source worktree;
- фиксирует exact source SHA;
- запускает тот же React application;
- сохраняет Playwright JSON result;
- сохраняет trace/screenshots при failure;
- сохраняет `manifest.json` и exit code;
- возвращает ненулевой код при любом browser failure.

Не передавайте credentials через URL (`https://user:password@...`): wrapper это запрещает. Если staging требует auth, используйте нормальный staging ingress/auth mechanism вне module scope.

## RSS observation

Browser acceptance сам по себе не доказывает server memory stability. Во время native staging run сохраните host/container observation для длинного stream.

Как минимум:

- NGINX master/worker PID до/после;
- process RSS до/во время/после long-stream scenario;
- container restart count;
- отсутствие worker/master restart;
- timestamp/host identity.

M13 2h/8h controlled soak остаётся основным memory stability gate. Staging RSS observation — дополнительная проверка, что production installation/configuration не создаёт новую проблему.

## Практический rollback

Rollback должен переключить **тот же staging traffic** обратно на существующий Envoy path. Недостаточно проверить, что Envoy container запущен.

Сохраните:

- команду/изменение rollout controller, которым выполнено переключение;
- timestamp;
- effective routing/config после переключения;
- health/observability evidence.

После реального переключения повторите **тот же React suite**:

```bash
STAGING_ENDPOINT=https://staging.example/grpc-web \
STAGING_UNAVAILABLE_ENDPOINT=https://staging.example/grpc-web-unavailable \
STAGING_TIMEOUT_ENDPOINT=https://staging.example/grpc-web-timeout \
STAGING_BROWSER=chromium \
STAGING_LABEL=envoy-rollback \
STAGING_OUTPUT_DIR=/data/nginx-grpc-web/staging/envoy-rollback/browser \
./scripts/run-staging-browser.sh
```

Здесь URL может остаться тем же: ценность теста как раз в том, что внешний клиент не знает, какой gateway path выбран rollout layer.

Успешный rollback означает одновременно:

```text
routing switched to Envoy
same external endpoint still works
same React/grpc-web suite passes
rollback did not require frontend code/config changes
```

## Что сохранить

Минимальный staging evidence tree:

```text
staging/
├── native/
│   ├── nginx-V.txt
│   ├── nginx-T.txt
│   ├── deployed-module.sha256
│   ├── rss-observation.*
│   └── browser/
│       ├── manifest.json
│       ├── playwright-exit-code.txt
│       └── browser-test-results/
├── envoy-rollback/
│   ├── routing-change.*
│   └── browser/
│       ├── manifest.json
│       ├── playwright-exit-code.txt
│       └── browser-test-results/
└── notes.md
```

## Acceptance

Staging считается закрытым только если:

- deployed module checksum совпадает с exact-commit package;
- `nginx -T` сохранён;
- native React suite green;
- incremental streaming доказан промежуточным состоянием `events > 0 && status == running`;
- canonical failure codes 3/4/14 проходят;
- cancellation проходит;
- long-stream observation не показывает restart/очевидный memory regression;
- rollout действительно переключён на Envoy;
- тот же React suite green после rollback;
- все evidence artifacts сохранены.

После этого rollback pool **не удаляется автоматически**. Его удаление — отдельное решение после production canary/observation window из `docs/ROLLOUT.md`.
