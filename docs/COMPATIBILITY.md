# Compatibility matrix

Актуально на 2026-08-15.

## NGINX

Для v0.1 CI поддерживает две текущие upstream-линии NGINX:

| Линия | Версия | Статус v0.1 |
|---|---:|---|
| stable | 1.30.4 | основной production target |
| mainline | 1.31.3 | compatibility target |

Официальная страница загрузки NGINX на дату фиксации матрицы:
`https://nginx.org/en/download.html`

История релизов 2026:
`https://nginx.org/2026.html`

Ранее проект собирался на 1.30.2 / 1.31.1. Эти версии больше не являются рекомендуемыми production targets: NGINX 1.30.3 / 1.31.2 содержат security fix CVE-2026-42055, затрагивающий в том числе `ngx_http_grpc_module`. M8 поэтому переводит CI на 1.30.4 / 1.31.3.

Поддержка означает не только `make modules`: CI собирает dynamic module и затем реально загружает `.so` в соответствующий официальный `nginx:<version>` image через `nginx -t`.

## Компиляторы

Dynamic module build matrix:

- GCC;
- Clang.

Оба компилятора проверяются на stable и mainline NGINX.

Это compiler compatibility gate, а не обещание ABI-переносимости произвольного `.so` между разными Linux-дистрибутивами.

## Dynamic-module ABI contract

Модуль собирается с:

```text
--with-compat
--add-dynamic-module=<repo>
```

Официальная документация NGINX:

- `https://nginx.org/en/docs/configure.html`
- `https://nginx.org/en/docs/switches.html`

`--with-compat` предназначен для совместимости dynamic modules между NGINX builds с различающимися configure options. При этом бинарный artifact всё равно следует рассматривать как привязанный к платформе и целевой NGINX-линии.

Перед установкой в существующий NGINX обязательно выполнить:

```bash
nginx -V
```

Если целевой binary не содержит `--with-compat`, безопасный вариант — собирать модуль с configure-параметрами этого конкретного NGINX build либо не использовать готовый `.so`.

## Browser matrix

M8 проверяет настоящий React + `grpc-web` runtime в трёх Playwright engines:

- Chromium;
- Firefox;
- WebKit.

Browser matrix запускается против NGINX stable 1.30.4 и того же Envoy reference oracle.

WebKit Playwright — полезный compatibility gate для WebKit engine, но не заменяет отдельную acceptance-проверку конкретной retail-версии Safari/iOS в инфраструктуре продукта, если она входит в официальный support SLA.

## Протокольный scope v0.1

Поддерживаются:

- `application/grpc-web`;
- `application/grpc-web+proto`;
- `application/grpc-web-text`;
- `application/grpc-web-text+proto`;
- unary;
- server-side streaming;
- metadata/trailers/status;
- cancellation/deadline;
- выбранные local gateway failures, нормализованные в terminal gRPC-Web status.

Не поддерживаются:

- client streaming;
- bidirectional streaming;
- grpc-web JSON;
- CORS/auth/routing/service discovery как функциональность модуля.

## Что считается green compatibility result

1. `.so` собирается GCC и Clang для stable/mainline.
2. `.so` реально загружается соответствующим NGINX binary.
3. Полный protocol/hardening/differential suite проходит на stable и mainline.
4. Browser suite проходит Chromium/Firefox/WebKit на stable.
5. Versioned packaging smoke формирует artifact + SHA256 + manifest.
