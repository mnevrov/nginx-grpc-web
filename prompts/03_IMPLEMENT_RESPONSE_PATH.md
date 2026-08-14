# Agent Prompt — Response Path

Реализуй downstream response adaptation.

## Scope

- response media type соответствует исходному grpc-web mode;
- stale `Content-Length` удалён;
- binary DATA semantics preserved;
- text response base64 корректен при произвольной fragmentation;
- gRPC frame boundaries не зависят от `ngx_chain_t`;
- zero-length frames;
- large allowed frames;
- overflow/size guard.

## Архитектурная подсказка

Для максимальной наблюдаемой совместимости можно собирать только текущий gRPC frame, а не весь stream.

State machine:

```text
READ_HEADER(5)
  -> validate length
  -> FORWARD/COLLECT CURRENT FRAME
  -> emit encoded frame
  -> READ_HEADER
```

Но сначала докажи тестом, какая buffering granularity реально необходима. Не копируй Envoy механически, если это создаёт лишнюю память и не требуется контрактом.

## Acceptance

- unary text response green;
- arbitrary fragmentation unit tests;
- no whole-stream buffer;
- differential semantic output equal to Envoy.
