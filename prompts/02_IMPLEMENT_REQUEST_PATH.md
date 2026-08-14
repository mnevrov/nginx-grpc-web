# Agent Prompt — Request Path

Реализуй request-side gRPC-Web adaptation test-first.

## Scope

1. activation только при `grpc_web on`;
2. detect supported grpc-web content types;
3. binary unary request passthrough;
4. text mode incremental base64 decode;
5. корректная native gRPC content type;
6. encoded `Content-Length` не должен стать upstream decoded length;
7. metadata не теряется;
8. malformed text request rejected.

## Особое внимание NGINX lifecycle

Request body проходит через `ngx_http_top_request_body_filter`.

Не изменяй incoming chain links in-place, если caller может ими владеть.

Decoder state хранить в per-request ctx.

Проверь поведение:

- quartet разбит 1/3;
- 2/2;
- 3/1;
- много NGINX buffers;
- final incomplete quartet;
- padding;
- empty body.

## Запреты

- не читать весь request в один буфер ради удобства;
- не парсить protobuf;
- не добавлять CORS;
- не менять browser code.

## Acceptance

Сначала unit fragmentation tests, затем integration against deterministic backend, затем differential Envoy/Nginx.
