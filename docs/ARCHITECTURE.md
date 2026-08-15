# Architecture

## 1. Production path

```text
Browser
  |
  | HTTP/1.1 or browser-managed HTTP/2
  | gRPC-Web
  v
NGINX worker
  |
  | ngx_http_grpc_web_module
  |   request body filter
  |   response header filter
  |   response body filter
  |   trailer encoder
  |
  | ngx_http_grpc_module
  v
Native gRPC backend over HTTP/2
```

## 2. Responsibility split

### ngx_http_grpc_web_module

Protocol adaptation only.

### ngx_http_grpc_module

Existing NGINX upstream transport:

- upstream connection;
- HTTP/2 framing;
- gRPC request/response transport;
- upstream parsing;
- backend trailers.

### Existing NGINX configuration

- TLS;
- route;
- auth;
- CORS if required;
- access logs;
- upstream balancing.

## 3. Why a dynamic module

Preferred over a core patch because:

- smaller maintenance surface;
- independent rollout;
- easier A/B against Envoy;
- rollback is removing `load_module`/directive;
- easier compatibility matrix.

A core patch is allowed only if a concrete lifecycle limitation is demonstrated by a minimal failing test and documented ADR.

## 4. Request state

Per-request context must contain at least:

```text
mode: inactive | binary | text
request base64 decoder state
response gRPC frame parser state
response base64 encoder state
trailers emitted flag
terminal/error state
```

No global mutable protocol state.

## 5. Streaming

The module must transform incrementally.

Correct:

```text
backend frame 1 -> transform -> browser event 1
delay
backend frame 2 -> transform -> browser event 2
```

Incorrect:

```text
backend frame 1
backend frame 2
backend frame 3
end
-> one accumulated output
```

## 6. Trailer path

Native gRPC trailers:

```text
grpc-status: 0
grpc-message:
x-test-trailer: value
```

become a gRPC-Web trailer body frame:

```text
0x80
uint32_be(length)
ascii trailer block
```

For text mode that frame is base64 encoded before downstream output.

## 7. Error path

The module must distinguish:

- valid gRPC error expressed by `grpc-status`;
- upstream transport failure;
- invalid grpc-web request;
- NGINX-generated HTTP error.

Behavior must be recorded in differential tests against Envoy and consumed correctly by real `grpc-web` runtime.
