# v0.1 release checklist

## Source and scope

- [ ] release commit находится в `main`;
- [ ] `README.md`, `docs/PROTOCOL_CONTRACT.md`, `docs/COMPATIBILITY.md` и `docs/DEPLOYMENT.md` соответствуют коду;
- [ ] scope v0.1 не расширен на client streaming, bidi, JSON, CORS/auth/routing;
- [ ] нет незакоммиченных/generated build artifacts в source tree.

## Compatibility CI

- [ ] NGINX stable 1.30.4 + GCC build/load smoke green;
- [ ] NGINX stable 1.30.4 + Clang build/load smoke green;
- [ ] NGINX mainline 1.31.3 + GCC build/load smoke green;
- [ ] NGINX mainline 1.31.3 + Clang build/load smoke green;
- [ ] full protocol/hardening/differential suite green на 1.30.4;
- [ ] full protocol/hardening/differential suite green на 1.31.3;
- [ ] Chromium browser suite green;
- [ ] Firefox browser suite green;
- [ ] WebKit browser suite green;
- [ ] ASAN/UBSAN green;
- [ ] Base64/frame fuzz smoke green.

## Security / hardening

- [ ] exact media-type activation regression green;
- [ ] malformed/incomplete Base64 regression green;
- [ ] oversized/truncated frame regressions green;
- [ ] missing native trailers cannot produce false success;
- [ ] repeated cancellation/reset RSS gates green;
- [ ] payload/Authorization secret logging regression green.

## Artifact

Versioned artifact naming recommendation:

```text
ngx_http_grpc_web_module-v0.1.0-nginx-1.30.4-linux-amd64-gcc.so
```

Каждый binary artifact должен сопровождаться:

- exact project tag/commit;
- exact NGINX version;
- compiler;
- OS/architecture/build environment;
- `--with-compat` declaration;
- SHA256 checksum;
- compatibility disclaimer для vendor/distro NGINX packages.

Для Docker-produced artifact:

```bash
make package-module NGINX_VERSION=1.30.4 BUILD_CC=gcc
```

Перед публикацией проверить `MANIFEST.txt` и `SHA256SUMS`.

Не публиковать один generic `.so` с обещанием совместимости со всеми NGINX packages.

## Release tag

Рекомендуемый первый tag:

```text
v0.1.0
```

Tag должен указывать на exact green commit после merge M8.

## Pre-production acceptance

- [ ] module artifact установлен в staging тем же способом, что и production;
- [ ] `nginx -t` green;
- [ ] effective config сохранён через `nginx -T`;
- [ ] real React client unary binary green;
- [ ] real React client grpc-web-text unary green;
- [ ] real React client server streaming incremental green;
- [ ] non-zero status/message green;
- [ ] cancellation/deadline green;
- [ ] unavailable/timeout green;
- [ ] long stream/RSS observation green;
- [ ] rollback path operationally tested.

## Production rollout

Следовать `docs/ROLLOUT.md`.

- [ ] baseline captured;
- [ ] 1% canary;
- [ ] 5-10%;
- [ ] 25-50%;
- [ ] 100%;
- [ ] Envoy rollback pool сохранён на agreed rollback window;
- [ ] removal Envoy оформляется отдельным change после стабильного observation window.

## Post-release

- [ ] сохранить CI run URL/ID в release notes;
- [ ] сохранить checksums published artifacts;
- [ ] зафиксировать NGINX compatibility matrix датой;
- [ ] при новом stable/mainline NGINX обновлять matrix отдельным compatibility PR;
- [ ] security releases NGINX, особенно изменения `ngx_http_grpc_module`, имеют приоритет над обычным release cadence проекта.
