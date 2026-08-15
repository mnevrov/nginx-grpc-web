ARG NGINX_VERSION=1.30.4

FROM debian:bookworm-slim AS build
ARG NGINX_VERSION
ARG BUILD_CC=gcc

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates clang curl libpcre2-dev zlib1g-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN curl -fsSLO "https://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz" && \
    tar xzf "nginx-${NGINX_VERSION}.tar.gz"

COPY . /module

WORKDIR "/build/nginx-${NGINX_VERSION}"
RUN ./configure \
      --with-cc="${BUILD_CC}" \
      --with-compat \
      --with-http_ssl_module \
      --with-http_v2_module \
      --add-dynamic-module=/module && \
    make modules

FROM scratch AS module-artifact
ARG NGINX_VERSION
COPY --from=build \
  /build/nginx-${NGINX_VERSION}/objs/ngx_http_grpc_web_module.so \
  /ngx_http_grpc_web_module.so

FROM nginx:${NGINX_VERSION} AS runtime
COPY --from=build \
  /build/nginx-${NGINX_VERSION}/objs/ngx_http_grpc_web_module.so \
  /etc/nginx/modules/ngx_http_grpc_web_module.so

RUN printf '%s\n' \
      'load_module /etc/nginx/modules/ngx_http_grpc_web_module.so;' \
      'events {}' \
      'http {}' \
      > /tmp/grpc-web-module-smoke.conf && \
    nginx -t -c /tmp/grpc-web-module-smoke.conf && \
    rm -f /tmp/grpc-web-module-smoke.conf

COPY docker/nginx/nginx.conf /etc/nginx/nginx.conf
