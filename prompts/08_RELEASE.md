# Agent Prompt — Release Candidate

Подготовь v0.1 release candidate только после выполнения `docs/DEFINITION_OF_DONE.md`.

## Проверки

- supported NGINX stable/mainline builds;
- module loads with `load_module`;
- `nginx -t`;
- Envoy differential suite;
- browser suite;
- ASAN/UBSAN;
- long streaming soak;
- rollback path.

## Документы

Обнови:

- README status;
- compatibility matrix;
- example NGINX config;
- migration from Envoy;
- limitations;
- changelog/release notes.

## Rollout strategy

Рекомендуй staged deployment:

```text
shadow/reference tests
-> dev
-> small canary
-> percentage traffic
-> remove Envoy only after observation window
```

Не удалять fallback Envoy из deployment в том же change, которым впервые включается module production-wide.
