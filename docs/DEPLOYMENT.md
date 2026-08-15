# Deployment and operations

## 1. Выбор способа установки

Есть два безопасных варианта.

### Вариант A — собственный NGINX image

Это рекомендуемый путь, если production уже контейнеризирован.

Репозиторий содержит multi-stage `docker/nginx/Dockerfile`, который:

1. скачивает исходники точной версии NGINX;
2. собирает `ngx_http_grpc_web_module.so` с `--with-compat`;
3. копирует модуль в официальный `nginx:<version>` image;
4. выполняет реальный `load_module` smoke через `nginx -t`.

Пример:

```bash
docker build \
  --build-arg NGINX_VERSION=1.30.4 \
  --build-arg BUILD_CC=gcc \
  -f docker/nginx/Dockerfile \
  -t company/nginx-grpc-web:1.30.4-v0.1 .
```

### Вариант B — dynamic module для существующего NGINX

Сначала зафиксировать target binary:

```bash
nginx -v
nginx -V
```

Проверить:

- точную версию NGINX;
- платформу/архитектуру;
- наличие `--with-compat`;
- modules path/configuration conventions конкретного пакета.

Не переносить `.so` вслепую между разными vendor packages или дистрибутивами.

Для официального NGINX-compatible artifact из текущего Docker build:

```bash
make package-module NGINX_VERSION=1.30.4 BUILD_CC=gcc
```

Результат:

```text
dist/nginx-1.30.4-gcc-linux-<arch>/
  ngx_http_grpc_web_module.so
  SHA256SUMS
  MANIFEST.txt
```

Artifact contract описан в `docs/COMPATIBILITY.md`.

## 2. Подключение модуля

Разместить `.so` в module directory целевого NGINX и добавить на верхнем уровне конфигурации:

```nginx
load_module modules/ngx_http_grpc_web_module.so;
```

Минимальный location:

```nginx
location /example.v1.ExampleService/ {
    grpc_web on;
    grpc_web_max_frame_size 64m;

    grpc_read_timeout 1h;
    grpc_send_timeout 1h;

    grpc_pass grpc://grpc_backend;
}
```

Полный пример: `examples/nginx-grpc-web.conf`.

## 3. Preflight перед reload

Обязательный порядок:

```bash
nginx -t
nginx -T > /secure/change-record/nginx-effective.conf
```

После успешной проверки:

```bash
nginx -s reload
```

Reload NGINX запускает новые workers с новой конфигурацией и graceful shutdown старых workers. Активные длинные streams поэтому не следует принудительно обрывать при обычном rollout.

## 4. Что не переносить в модуль

`ngx_http_grpc_web_module` не должен становиться policy layer.

Оставить штатным NGINX/инфраструктуре:

- TLS termination;
- CORS;
- authentication/authorization;
- route selection;
- load balancing;
- retries/circuit breakers;
- service discovery;
- rate limiting.

Если browser и API находятся на разных origins, CORS настраивается обычной NGINX/edge-конфигурацией. Отсутствие CORS логики внутри модуля является намеренным architectural boundary.

## 5. Observability

### Gateway-level signals

Минимально собирать:

- `$status`;
- `$upstream_status`;
- `$request_time`;
- `$upstream_response_time`;
- `$bytes_sent`;
- 499/client disconnect rate;
- worker RSS/CPU;
- active downstream connections;
- upstream connect/reset/timeout errors из `error_log`.

Пример `log_format` находится в `examples/nginx-grpc-web.conf`.

### Важное ограничение HTTP metrics

gRPC/gRPC-Web application errors обычно остаются HTTP 200. Поэтому `$status=200` не означает `grpc-status=0`.

Также M6 нормализует выбранные local gateway failures в корректный terminal gRPC-Web frame; downstream HTTP status после такой адаптации может быть 200, тогда как `$upstream_status` сохраняет полезный сигнал о 502/503/504 источнике ошибки.

Поэтому application-level SLI следует строить по одному или нескольким источникам:

- backend gRPC metrics/status codes;
- client-side grpc-web telemetry;
- distributed tracing;
- service-level counters.

Не включать request body или `Authorization` в access/error logs ради извлечения grpc-status. M7 отдельно regression-тестирует отсутствие таких secrets в module logs.

### Streaming-specific signals

Для server streaming полезно отдельно измерять:

- time-to-first-DATA;
- stream duration;
- disconnect/cancel rate;
- bytes per stream;
- worker RSS under long streams.

Обычная request latency скрывает проблемы с first-message buffering.

## 6. Configuration verification после reload

Проверить минимум:

1. binary unary;
2. grpc-web-text unary;
3. server streaming с наблюдаемым первым DATA до EOF;
4. non-zero grpc-status/grpc-message;
5. cancellation;
6. backend unavailable/timeout;
7. один длинный stream;
8. отсутствие неожиданных 5xx/worker restarts.

Для автоматизированного pre-production smoke можно использовать тестовый harness репозитория, но production acceptance должна обращаться к реальным service methods и реальному React client.
