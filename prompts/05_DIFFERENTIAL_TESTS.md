# Agent Prompt — Differential Harness

Построй один reusable harness, который гоняет одинаковый scenario через:

- Envoy reference;
- NGINX module.

## Canonical result

Сравнивать semantic representation:

```text
headers/metadata (allowlist)
decoded data frame payloads
trailer map
grpc status/message
event order
terminal state
arrival timing class
```

Не требовать identical:

- TCP packets;
- HTTP chunk boundaries;
- base64 chunk boundaries;
- internal proxy headers.

## Scenarios

Используй матрицу из `docs/TEST_STRATEGY.md`.

Каждый новый protocol bug должен сначала добавляться как scenario, воспроизводящий различие Envoy vs NGINX.

## Output

При mismatch печатай:

- scenario;
- canonical Envoy result;
- canonical NGINX result;
- first semantic difference;
- raw capture только при debug flag, чтобы CI logs не утекали metadata/payload случайно.
