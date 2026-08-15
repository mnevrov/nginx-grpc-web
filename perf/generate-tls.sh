#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CERT_DIR=${1:-"$ROOT/perf/.certs"}

command -v openssl >/dev/null 2>&1 || {
  echo "openssl is required for TLS benchmark certificate generation" >&2
  exit 1
}

umask 077
rm -rf "$CERT_DIR"
mkdir -p "$CERT_DIR"

openssl req \
  -x509 \
  -newkey rsa:2048 \
  -sha256 \
  -nodes \
  -days 2 \
  -subj "/CN=nginx-grpc-web-perf-ca" \
  -keyout "$CERT_DIR/ca.key" \
  -out "$CERT_DIR/ca.crt" \
  >/dev/null 2>&1

openssl req \
  -newkey rsa:2048 \
  -sha256 \
  -nodes \
  -subj "/CN=localhost" \
  -keyout "$CERT_DIR/server.key" \
  -out "$CERT_DIR/server.csr" \
  >/dev/null 2>&1

cat > "$CERT_DIR/server.ext" <<'EOF'
subjectAltName=DNS:localhost,IP:127.0.0.1
extendedKeyUsage=serverAuth
keyUsage=digitalSignature,keyEncipherment
EOF

openssl x509 \
  -req \
  -sha256 \
  -days 2 \
  -in "$CERT_DIR/server.csr" \
  -CA "$CERT_DIR/ca.crt" \
  -CAkey "$CERT_DIR/ca.key" \
  -CAcreateserial \
  -extfile "$CERT_DIR/server.ext" \
  -out "$CERT_DIR/server.crt" \
  >/dev/null 2>&1

rm -f "$CERT_DIR/ca.key" "$CERT_DIR/ca.srl" "$CERT_DIR/server.csr" "$CERT_DIR/server.ext"
chmod 0644 "$CERT_DIR/ca.crt" "$CERT_DIR/server.crt"
chmod 0600 "$CERT_DIR/server.key"

printf 'generated TLS benchmark certificate: %s\n' "$CERT_DIR"
