#!/usr/bin/env bash
set -euo pipefail

NGINX_VERSION="${NGINX_VERSION:-1.30.4}"
BUILD_CC="${BUILD_CC:-gcc}"
OUT_ROOT="${OUT_ROOT:-dist}"
ARCH="$(uname -m)"
PACKAGE_DIR="${OUT_ROOT}/nginx-${NGINX_VERSION}-${BUILD_CC}-linux-${ARCH}"

rm -rf "${PACKAGE_DIR}"
mkdir -p "${PACKAGE_DIR}"

docker build \
  --target module-artifact \
  --build-arg "NGINX_VERSION=${NGINX_VERSION}" \
  --build-arg "BUILD_CC=${BUILD_CC}" \
  --output "type=local,dest=${PACKAGE_DIR}" \
  -f docker/nginx/Dockerfile \
  .

MODULE_PATH="${PACKAGE_DIR}/ngx_http_grpc_web_module.so"
test -f "${MODULE_PATH}"

sha256sum "${MODULE_PATH}" > "${PACKAGE_DIR}/SHA256SUMS"
cat > "${PACKAGE_DIR}/MANIFEST.txt" <<EOF
module=ngx_http_grpc_web_module.so
nginx_version=${NGINX_VERSION}
compiler=${BUILD_CC}
platform=linux-${ARCH}
build_mode=--with-compat
source_commit=$(git rev-parse HEAD 2>/dev/null || printf 'unknown')

Compatibility contract:
- this artifact is validated against the official nginx:${NGINX_VERSION} container image;
- do not assume ABI compatibility with arbitrary distro/vendor nginx packages;
- for an existing installation, inspect 'nginx -V' and rebuild on the target platform when in doubt.
EOF

printf 'created %s\n' "${PACKAGE_DIR}"
cat "${PACKAGE_DIR}/SHA256SUMS"
