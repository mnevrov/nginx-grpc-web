# Agent Prompt — M0 Reference Oracle

Задача: довести reference harness Envoy до состояния, при котором он надёжно фиксирует ожидаемое поведение gRPC-Web до реализации NGINX module.

## Требования

Добавь/проверь сценарии:

- unary grpc-web-text success;
- unary grpc-web binary success;
- server streaming;
- non-zero grpc status;
- grpc-message;
- custom trailers;
- trailers-only;
- empty stream;
- cancellation;
- backend reset/unavailable;
- fragmented/raw text request cases.

## Oracle rules

Не фиксируй TCP/HTTP chunk boundaries как API.

Нормализуй результат к структуре:

```json
{
  "data_frames": ["hex-or-base64 payload", "..."],
  "trailers": {"grpc-status": "0"},
  "metadata": {},
  "terminal": "end|error|cancel"
}
```

Для streaming дополнительно сохраняй monotonic arrival timestamps относительно старта.

## Definition of done

- `make reference-up`;
- reference test suite green;
- tests deterministic;
- нет NGINX module assumptions;
- browser grpc-web client реально проходит Envoy path.
