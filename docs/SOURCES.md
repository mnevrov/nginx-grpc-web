# Authoritative Sources

Use primary sources when resolving protocol or NGINX lifecycle questions.

## gRPC-Web

- Protocol specification: https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-WEB.md
- Official client/generator: https://github.com/grpc/grpc-web
- Envoy gRPC-Web filter docs: https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/grpc_web_filter
- Envoy filter source: https://github.com/envoyproxy/envoy/tree/main/source/extensions/filters/http/grpc_web

## NGINX

- Development guide: https://nginx.org/en/docs/dev/development_guide.html
- gRPC module docs: https://nginx.org/en/docs/http/ngx_http_grpc_module.html
- NGINX source: https://github.com/nginx/nginx
- grpc module source: https://github.com/nginx/nginx/blob/master/src/http/modules/ngx_http_grpc_module.c
- upstream source: https://github.com/nginx/nginx/blob/master/src/http/ngx_http_upstream.c

## Version baseline at repository bootstrap

- NGINX stable test baseline: 1.30.2
- NGINX mainline test baseline: 1.31.1
- Envoy reference image baseline: 1.38.0

Versions are CI baselines, not protocol contracts. Keep compatibility tests broader than one exact patch version.
