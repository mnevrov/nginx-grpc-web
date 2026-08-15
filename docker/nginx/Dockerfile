ARG NGINX_VERSION=1.30.2

FROM debian:bookworm-slim AS build
ARG NGINX_VERSION

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl libpcre2-dev zlib1g-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN curl -fsSLO "https://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz" && \
    tar xzf "nginx-${NGINX_VERSION}.tar.gz"

COPY . /module

WORKDIR "/build/nginx-${NGINX_VERSION}"
RUN ./configure \
      --with-compat \
      --with-http_ssl_module \
      --with-http_v2_module \
      --add-dynamic-module=/module && \
    make modules

FROM nginx:${NGINX_VERSION}
COPY --from=build \
  /build/nginx-${NGINX_VERSION}/objs/ngx_http_grpc_web_module.so \
  /etc/nginx/modules/ngx_http_grpc_web_module.so
COPY docker/nginx/nginx.conf /etc/nginx/nginx.conf
