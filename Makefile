.PHONY: help unit sanitizers fuzz-smoke reference-up module-up down test-reference test-module test-diff test-browser package-module perf-loadgen-test perf-capacity-test perf-soak-test release-evidence-test release-check rc-benchmark-test rc-soak-test staging-evidence-test m15-evidence-test rc-benchmark rc-soak rc-release-check staging-browser staging-evidence m15-check perf-smoke perf-typical perf-large perf-slow perf-h2-smoke perf-h2-typical perf-h2-large perf-h2-slow perf-capacity-smoke perf-h2-capacity-smoke perf-capacity perf-h2-capacity perf-soak-smoke perf-soak perf-down lint archive

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
	  'make perf-loadgen-test - Go loadgen protocol/unit tests' \
	  'make perf-capacity-test - pure Python SLO/capacity tests' \
	  'make perf-soak-test  - pure Python soak trend/lifecycle tests' \
	  'make release-evidence-test - pure Python M14/M15 release evidence tests' \
	  'make release-check   - build/validate self-contained v0.1.0 RC evidence bundle' \
	  'make rc-benchmark-test - pure Python M15 controlled-RC evaluator tests' \
	  'make rc-soak-test    - pure Python M15 benchmark/soak provenance tests' \
	  'make staging-evidence-test - pure Python M15 staging/rollback evidence tests' \
	  'make m15-evidence-test - pure Python final M15 release-readiness tests' \
	  'make rc-benchmark    - strict controlled-host RC benchmark; requires explicit SLOs and isolated CPU sets' \
	  'make rc-soak         - strict >=2h soak tied to a completed RC benchmark host/source' \
	  'make rc-release-check - feed selected M15 benchmark/soak into M14 controlled release evidence' \
	  'make staging-browser - run unchanged React/grpc-web client against external staging endpoints' \
	  'make staging-evidence - validate deployed package, native staging and Envoy rollback evidence' \
	  'make m15-check       - aggregate benchmark/soak/staging/M14 evidence; never creates tag/release' \
	  'make perf-smoke      - HTTP/1.1 short A/B topology + report validation' \
	  'make perf-typical    - HTTP/1.1 4 KiB server-stream concurrency A/B' \
	  'make perf-large      - HTTP/1.1 1/4/8 MiB text+binary A/B sweep' \
	  'make perf-slow       - HTTP/1.1 slow-consumer/backpressure A/B sweep' \
	  'make perf-h2-smoke   - TLS/HTTP2 strict A/B topology + report validation' \
	  'make perf-h2-typical - TLS/HTTP2 4 KiB concurrency A/B' \
	  'make perf-h2-large   - TLS/HTTP2 1/4/8 MiB text+binary A/B sweep' \
	  'make perf-h2-slow    - TLS/HTTP2 slow-consumer/backpressure A/B sweep' \
	  'make perf-capacity-smoke - bounded HTTP/1 SLO staircase harness check' \
	  'make perf-h2-capacity-smoke - bounded TLS/H2 SLO staircase harness check' \
	  'make perf-capacity   - HTTP/1 capacity staircase; requires PERF_CAPACITY_SLO' \
	  'make perf-h2-capacity - TLS/H2 capacity staircase; requires PERF_CAPACITY_SLO' \
	  'make perf-soak-smoke - bounded TLS/H2 lifecycle soak harness check' \
	  'make perf-soak       - strict controlled TLS/H2 soak; requires isolated CPU sets' \
	  'make perf-down       - stop performance topology' \
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
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) bash ./scripts/package-module.sh

perf-loadgen-test:
	cd perf/loadgen && go test ./...

perf-capacity-test:
	python3 perf/test_capacity.py -q

perf-soak-test:
	python3 perf/test_soak.py -q

release-evidence-test:
	python3 -m unittest discover -s release -p 'test_*.py' -q

release-check:
	bash ./scripts/release-check.sh

rc-benchmark-test:
	python3 perf/test_rc.py -q

rc-soak-test:
	python3 perf/test_rc_soak.py -q

staging-evidence-test:
	python3 staging/test_evidence.py -q

m15-evidence-test:
	python3 release/test_m15.py -q

rc-benchmark:
	bash ./perf/run-rc.sh

rc-soak:
	bash ./perf/run-rc-soak.sh

rc-release-check:
	bash ./scripts/rc-release-check.sh

staging-browser:
	bash ./scripts/run-staging-browser.sh

staging-evidence:
	bash ./scripts/staging-evidence.sh

m15-check:
	bash ./scripts/m15-check.sh

perf-smoke:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) PERF_FRONTEND=http1 bash ./perf/run-ab.sh smoke

perf-typical:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) PERF_FRONTEND=http1 bash ./perf/run-ab.sh typical

perf-large:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) PERF_FRONTEND=http1 bash ./perf/run-ab.sh large

perf-slow:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) PERF_FRONTEND=http1 bash ./perf/run-ab.sh slow

perf-h2-smoke:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) PERF_FRONTEND=tls-h2 bash ./perf/run-ab.sh smoke

perf-h2-typical:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) PERF_FRONTEND=tls-h2 bash ./perf/run-ab.sh typical

perf-h2-large:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) PERF_FRONTEND=tls-h2 bash ./perf/run-ab.sh large

perf-h2-slow:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) PERF_FRONTEND=tls-h2 bash ./perf/run-ab.sh slow

perf-capacity-smoke:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) PERF_FRONTEND=http1 PERF_CAPACITY_SLO=perf/scenarios/capacity-smoke-slo.json PERF_CAPACITY_STEPS=$${PERF_CAPACITY_STEPS:-1,2} PERF_CAPACITY_MESSAGES=$${PERF_CAPACITY_MESSAGES:-2} PERF_CAPACITY_DELAY_MS=$${PERF_CAPACITY_DELAY_MS:-5} bash ./perf/run-ab.sh capacity

perf-h2-capacity-smoke:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) PERF_FRONTEND=tls-h2 PERF_CAPACITY_SLO=perf/scenarios/capacity-smoke-slo.json PERF_CAPACITY_STEPS=$${PERF_CAPACITY_STEPS:-1,2} PERF_CAPACITY_MESSAGES=$${PERF_CAPACITY_MESSAGES:-2} PERF_CAPACITY_DELAY_MS=$${PERF_CAPACITY_DELAY_MS:-5} bash ./perf/run-ab.sh capacity

perf-capacity:
	@test -n "$(PERF_CAPACITY_SLO)" || (echo 'PERF_CAPACITY_SLO=/path/to/slo.json is required' >&2; exit 2)
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) PERF_FRONTEND=http1 PERF_CAPACITY_SLO=$(PERF_CAPACITY_SLO) bash ./perf/run-ab.sh capacity

perf-h2-capacity:
	@test -n "$(PERF_CAPACITY_SLO)" || (echo 'PERF_CAPACITY_SLO=/path/to/slo.json is required' >&2; exit 2)
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) PERF_FRONTEND=tls-h2 PERF_CAPACITY_SLO=$(PERF_CAPACITY_SLO) bash ./perf/run-ab.sh capacity

perf-soak-smoke:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) SOAK_STRICT=0 SOAK_POLICY=perf/scenarios/soak-smoke.json SOAK_DURATION_SECONDS=$${SOAK_DURATION_SECONDS:-8} SOAK_STATS_INTERVAL=$${SOAK_STATS_INTERVAL:-0.10} SOAK_STEADY_STREAMS=$${SOAK_STEADY_STREAMS:-2} SOAK_STEADY_MESSAGES=$${SOAK_STEADY_MESSAGES:-20} SOAK_CHURN_STREAMS=$${SOAK_CHURN_STREAMS:-4} SOAK_CANCEL_STREAMS=$${SOAK_CANCEL_STREAMS:-4} SOAK_RESET_STREAMS=$${SOAK_RESET_STREAMS:-2} SOAK_RESTART_STREAMS=$${SOAK_RESTART_STREAMS:-3} bash ./perf/run-soak.sh

perf-soak:
	NGINX_VERSION=$(NGINX_VERSION) BUILD_CC=$(BUILD_CC) SOAK_STRICT=1 bash ./perf/run-soak.sh

perf-down:
	docker compose -f perf/docker-compose.perf.yml down -v
