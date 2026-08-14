# Agent Prompt — Hardening

Проведи security/reliability pass после функциональной совместимости.

## Проверить

- integer overflow при frame length;
- max frame size enforcement;
- malformed/incomplete base64;
- incomplete 5-byte header;
- EOF mid-frame;
- duplicate terminal trailers;
- huge custom trailers;
- slow client;
- backend reset;
- cancellation на каждой стадии state machine;
- NGINX reload/worker shutdown;
- memory retention across long stream.

## Tooling

Добавь и реально запусти по возможности:

- ASAN;
- UBSAN;
- compiler warnings as errors;
- fuzz harness для pure base64/frame code;
- long-stream soak.

## Security rule

Не логировать protobuf payload, authorization metadata или arbitrary request metadata на error path.
