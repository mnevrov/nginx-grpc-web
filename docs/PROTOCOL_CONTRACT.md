# gRPC-Web Protocol Contract

Это рабочий контракт проекта. При споре агент обязан сверяться с официальной gRPC-Web specification и текущим Envoy filter.

## Media types

Recognize case-insensitively where HTTP semantics require it:

- `application/grpc-web`
- `application/grpc-web+proto`
- `application/grpc-web-text`
- `application/grpc-web-text+proto`

Не активировать модуль для обычного `application/grpc`.

## Request transformation

### Binary mode

Body protobuf/gRPC framing остаётся opaque и передаётся upstream без base64 decode.

### Text mode

Body — base64 representation. Decode incrementally.

Нельзя ожидать:

- quartet целиком в одном NGINX buffer;
- целый gRPC frame в одном buffer;
- совпадение HTTP chunk с frame.

Malformed final base64 должен завершать запрос предсказуемой ошибкой.

### Headers

Downstream gRPC-Web request должен стать native gRPC request для `ngx_http_grpc_module`.

Минимальные семантические требования:

- upstream content type: `application/grpc`;
- старый encoded `Content-Length` не должен использоваться как decoded length;
- metadata headers, разрешённые NGINX/grpc path, сохраняются;
- protocol-only browser headers не должны ломать backend.

## Native gRPC frame

```text
+------------+--------------------+------------------+
| flags 1 B  | length uint32 BE   | payload N bytes  |
+------------+--------------------+------------------+
```

Payload не интерпретируется.

## Response transformation

### Binary mode

Native gRPC DATA bytes могут быть переданы в gRPC-Web binary framing без protobuf parsing.

### Text mode

Output base64 encoding state не может зависеть от границ NGINX chain buffers.

Для совместимости допустима канонизация по полным gRPC frames, но тесты не должны считать конкретные downstream chunk boundaries частью публичного API.

## Trailer frame

gRPC-Web trailers находятся в body:

```text
byte 0: 0x80
bytes 1..4: uint32 BE trailer block length
bytes 5..: trailer block
```

Trailer block — HTTP-style header lines с CRLF.

Обязательные semantics:

- `grpc-status`;
- `grpc-message` если присутствует;
- custom trailers если допустимы;
- frame идёт после всех data frames;
- frame отправляется ровно один раз.

## Trailers-only

Backend может завершить RPC без DATA frames. Browser всё равно должен получить валидное terminal status.

## Cancellation

Если browser отменяет server stream:

- downstream request должен завершиться;
- upstream gRPC request должен быть отменён/закрыт через нормальный NGINX lifecycle;
- не должно оставаться удерживаемых buffers/context вне request lifetime.

## Limits

До выделения памяти по длине из недоверенного frame:

- проверить integer overflow;
- проверить configured maximum;
- не выделять `5 + length` без верхней границы.

## Compression

v0.1 не реализует собственную compression/decompression. Биты/metadata не должны искажаться. Любой unsupported behavior должен быть явно протестирован и документирован.
