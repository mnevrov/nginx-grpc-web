.PHONY: help unit reference-up module-up down test-reference test-module test-diff test-browser lint archive

CC ?= cc
CFLAGS ?= -O2 -g -Wall -Wextra -Werror

help:
	@printf '%s\n' \
	  'make unit            - pure C + Python codec tests' \
	  'make reference-up    - backend + Envoy oracle' \
	  'make module-up       - backend + NGINX module' \
	  'make test-reference  - Envoy integration baseline' \
	  'make test-module     - NGINX integration tests (milestone gated)' \
	  'make test-browser    - browser grpc-web tests' \
	  'make down            - stop test stack'

build/unit-base64:
	@mkdir -p build
	$(CC) $(CFLAGS) -Isrc tests/unit/test_base64.c src/grpc_web_base64.c -o $@

build/unit-frame:
	@mkdir -p build
	$(CC) $(CFLAGS) -Isrc tests/unit/test_frame.c src/grpc_web_frame.c -o $@

unit: build/unit-base64 build/unit-frame
	./build/unit-base64
	./build/unit-frame
	python3 -m pytest -q tests/protocol/test_codec.py

reference-up:
	docker compose up -d --build backend envoy

module-up:
	docker compose up -d --build backend nginx

down:
	docker compose down -v

test-reference:
	python3 -m pytest -q -m integration tests/protocol/test_reference_smoke.py

test-module:
	@echo "M2+: add enabled module integration tests; see docs/IMPLEMENTATION_PLAN.md"

test-diff:
	@echo "M2+: differential harness is milestone-gated; see prompts/05_DIFFERENTIAL_TESTS.md"

test-browser:
	cd tests/browser && npm test
