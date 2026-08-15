.PHONY: help unit sanitizers fuzz-smoke reference-up module-up down test-reference test-module test-diff test-browser package-module lint archive

CC ?= cc
CFLAGS ?= -O2 -g -Wall -Wextra -Werror
FUZZ_CC ?= clang
FUZZ_CFLAGS ?= -O1 -g -fno-omit-frame-pointer -fsanitize=fuzzer,address,undefined -Wall -Wextra -Werror
SANITIZER_CFLAGS ?= -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -Wall -Wextra -Werror
BROWSER ?=
NGINX_VERSION ?= 1.30.4
BUILD_CC ?= gcc

help:
	@printf '%s\n' \
	  'make unit            - pure C + Python codec tests' \
	  'make sanitizers      - pure C tests under ASAN/UBSAN' \
	  'make fuzz-smoke      - bounded libFuzzer smoke for C state machines' \
	  'make reference-up    - backend + Envoy oracle' \
	  'make module-up       - backend + NGINX module' \
	  'make test-reference  - Envoy integration baseline' \
	  'make test-module     - NGINX implemented module integration tests' \
	  'make test-diff       - Envoy vs NGINX implemented differential tests' \
	  'make test-browser    - browser grpc-web tests; BROWSER=chromium|firefox|webkit optional' \
	  'make package-module  - export versioned .so from Docker; NGINX_VERSION/BUILD_CC configurable' \
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

sanitizers:
	@mkdir -p build/sanitizers
	$(CC) $(SANITIZER_CFLAGS) -Isrc tests/unit/test_base64.c src/grpc_web_base64.c -o build/sanitizers/unit-base64
	$(CC) $(SANITIZER_CFLAGS) -Isrc tests/unit/test_frame.c src/grpc_web_frame.c -o build/sanitizers/unit-frame
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./build/sanitizers/unit-base64
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./build/sanitizers/unit-frame

build/fuzz-base64:
	@mkdir -p build
	$(FUZZ_CC) $(FUZZ_CFLAGS) -Isrc tests/fuzz/fuzz_base64.c src/grpc_web_base64.c -o $@

build/fuzz-frame:
	@mkdir -p build
	$(FUZZ_CC) $(FUZZ_CFLAGS) -Isrc tests/fuzz/fuzz_frame.c src/grpc_web_frame.c -o $@

fuzz-smoke: build/fuzz-base64 build/fuzz-frame
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./build/fuzz-base64 -runs=20000 -max_len=512
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./build/fuzz-frame -runs=20000 -max_len=512

reference-up:
	docker compose up -d --build backend envoy

module-up:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) docker compose up -d --build backend nginx

down:
	docker compose down -v

test-reference:
	python3 -m pytest -q -m integration tests/protocol/test_reference_smoke.py

test-module:
	python3 -m pytest -q -m integration \
	  tests/protocol/test_module_binary.py::test_nginx_binary_unary \
	  tests/protocol/test_module_text_request.py::test_nginx_text_unary_fixed_content_length_decodes_request \
	  tests/protocol/test_module_text_request.py::test_nginx_text_unary_chunked_fragmentation \
	  tests/protocol/test_module_text_request.py::test_nginx_rejects_malformed_text_request \
	  tests/protocol/test_module_text_response.py::test_nginx_text_unary_response \
	  tests/protocol/test_module_text_response.py::test_nginx_text_response_fragmented_native_frame_matches_envoy \
	  tests/protocol/test_module_text_response.py::test_nginx_text_nonzero_status_and_message_match_envoy \
	  tests/protocol/test_module_streaming.py::test_nginx_text_server_stream_is_incremental \
	  tests/protocol/test_module_streaming.py::test_nginx_text_server_stream_large_frames_are_not_whole_stream_buffered \
	  tests/protocol/test_module_streaming.py::test_nginx_text_server_stream_survives_slow_consumer_backpressure \
	  tests/protocol/test_module_streaming.py::test_nginx_long_stream_does_not_retain_every_encoded_frame \
	  tests/protocol/test_module_failures.py::test_nginx_empty_stream_matches_envoy \
	  tests/protocol/test_module_failures.py::test_nginx_midstream_failure_matches_envoy \
	  tests/protocol/test_module_failures.py::test_nginx_grpc_timeout_matches_envoy \
	  tests/protocol/test_module_failures.py::test_nginx_client_disconnect_cancels_upstream \
	  tests/protocol/test_module_failures.py::test_nginx_unavailable_is_grpc_web_terminal_status \
	  tests/protocol/test_module_failures.py::test_nginx_proxy_timeout_is_grpc_web_terminal_status \
	  tests/protocol/test_module_hardening.py

test-diff:
	python3 -m pytest -q -m integration \
	  tests/protocol/test_module_binary.py::test_nginx_binary_unary_matches_envoy \
	  tests/protocol/test_module_text_request.py::test_nginx_text_request_semantics_match_envoy \
	  tests/protocol/test_module_text_response.py::test_nginx_text_unary_response_matches_envoy \
	  tests/protocol/test_module_text_response.py::test_nginx_text_nonzero_status_and_message_match_envoy \
	  tests/protocol/test_module_streaming.py::test_nginx_text_server_stream_matches_envoy_semantics_and_timing \
	  tests/protocol/test_module_failures.py::test_nginx_empty_stream_matches_envoy \
	  tests/protocol/test_module_failures.py::test_nginx_midstream_failure_matches_envoy \
	  tests/protocol/test_module_failures.py::test_nginx_grpc_timeout_matches_envoy

test-browser:
	cd tests/browser && npx playwright test $(if $(BROWSER),--project=$(BROWSER),)

package-module:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) ./scripts/package-module.sh
