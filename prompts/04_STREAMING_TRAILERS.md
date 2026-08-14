# Agent Prompt — Streaming + Trailers

Задача: завершить критический server-streaming path.

## Trailers

Найди точный момент NGINX lifecycle, когда upstream gRPC trailers уже доступны, а terminal downstream buffer ещё можно преобразовать.

Построй trailer frame:

```text
0x80
uint32_be(length)
name:value\r\n
...
```

Гарантируй:

- ровно один trailer frame;
- после всех DATA frames;
- `grpc-status` обязателен;
- `grpc-message` корректен;
- custom trailers сохранены в допустимом виде;
- trailers-only response работает.

## Streaming

Backend emit с задержкой. Browser должен видеть каждое событие до EOF.

Добавь regression test, который сломается при whole-stream buffering.

## Cancellation

Playwright/browser test должен:

1. открыть stream;
2. получить первое событие;
3. вызвать cancel;
4. доказать завершение upstream request;
5. убедиться, что backend не продолжает бессмысленно генерировать полный stream.

## Acceptance

Этот milestone не закрывается без настоящего `grpc-web` runtime test.
