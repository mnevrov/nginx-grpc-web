import base64
import os
import subprocess
import time

import httpx
import pytest

from grpc_web import (
    decode_frames,
    decode_text_body,
    encode_data_frame,
    iter_text_frames,
    parse_trailers,
)


MODULE = os.getenv("MODULE_URL", "http://127.0.0.1:18080")
FAULT_MODULE = os.getenv("NGINX_FAULT_URL", "http://127.0.0.1:18086")


def protobuf_string_field_1(value: str) -> bytes:
    raw = value.encode()
    assert len(raw) < 128
    return bytes([0x0A, len(raw)]) + raw


def post_with_content_type(content_type: str, *, text: bool = False) -> httpx.Response:
    frame = encode_data_frame(protobuf_string_field_1("media-type"))
    body = base64.b64encode(frame) if text else frame
    return httpx.post(
        f"{MODULE}/grpcwebtest.TestService/Unary",
        content=body,
        headers={
            "content-type": content_type,
            "x-grpc-web": "1",
            "accept": "application/grpc-web-text+proto" if text else "application/grpc-web+proto",
        },
        timeout=5,
    )


def assert_grpc_web_success(response: httpx.Response) -> None:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/grpc-web")

    if response.headers["content-type"].startswith("application/grpc-web-text"):
        # DATA and trailers may be independently Base64-encoded and therefore
        # may contain legal '=' padding before later encoded frames. Never
        # treat a complete grpc-web-text HTTP body as one Base64 document.
        frames = decode_text_body([response.content])
    else:
        frames = decode_frames(response.content)

    assert frames
    assert frames[-1].is_trailer
    assert parse_trailers(frames[-1].payload)["grpc-status"] == "0"


def text_headers(**extra: str) -> dict[str, str]:
    return {
        "content-type": "application/grpc-web-text+proto",
        "x-grpc-web": "1",
        "accept": "application/grpc-web-text+proto",
        **extra,
    }


def fault_request_body(mode: str) -> bytes:
    return base64.b64encode(
        encode_data_frame(protobuf_string_field_1(f"fault-{mode}"))
    )


def nginx_rss_kb() -> int:
    script = r'''
awk '
  /^Name:/ { is_nginx = ($2 == "nginx") }
  /^VmRSS:/ && is_nginx { sum += $2 }
  END { print sum + 0 }
' /proc/[0-9]*/status 2>/dev/null
'''
    raw = subprocess.check_output(
        ["docker", "compose", "exec", "-T", "nginx", "sh", "-c", script],
        text=True,
        timeout=5,
    )
    return int(raw.strip())


def consume_fault(mode: str) -> None:
    try:
        with httpx.stream(
            "POST",
            f"{FAULT_MODULE}/grpcwebtest.TestService/Stream",
            content=fault_request_body(mode),
            headers=text_headers(**{"x-fault-mode": mode}),
            timeout=3,
        ) as response:
            assert response.status_code == 200
            for _ in response.iter_raw():
                pass
    except httpx.HTTPError:
        # A filter/upstream transport failure after HTTP 200 may terminate the
        # HTTP/1 downstream connection rather than produce a complete body.
        pass


def observe_fault_frames(mode: str) -> list:
    timeout = httpx.Timeout(2.0, read=0.35)
    observed = []

    with httpx.stream(
        "POST",
        f"{FAULT_MODULE}/grpcwebtest.TestService/Stream",
        content=fault_request_body(mode),
        headers=text_headers(**{"x-fault-mode": mode}),
        timeout=timeout,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            "application/grpc-web-text"
        )

        frames = iter_text_frames(response.iter_raw())
        first = next(frames)
        assert not first.is_trailer
        observed.append(first)

        # Let the injected RST_STREAM/TCP reset/EOF become observable upstream,
        # then drain only a small bounded number of semantic frames. Envoy may
        # leave the browser RPC open after an after-DATA reset, so EOF, protocol
        # error and a bounded read timeout are all legitimate transport shapes.
        time.sleep(0.05)
        try:
            while len(observed) < 3:
                observed.append(next(frames))
        except (StopIteration, httpx.HTTPError, ValueError):
            pass

    return observed


def assert_main_path_still_healthy() -> None:
    assert_grpc_web_success(
        post_with_content_type("application/grpc-web-text+proto", text=True)
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("content_type", "text"),
    [
        ("application/grpc-web+json", False),
        ("application/grpc-web-text+json", True),
        ("application/grpc-web+protoevil", False),
        ("application/grpc-web-text+protoevil", True),
        ("application/grpc-web-garbage", False),
        ("application/grpc", False),
    ],
)
def test_nginx_does_not_activate_for_out_of_scope_media_types(content_type: str, text: bool):
    response = post_with_content_type(content_type, text=text)

    # Outside the v0.1 media-type contract the module must stay inactive.
    # The stock grpc_pass/backend may choose its own error representation, but
    # ngx_http_grpc_web_module must not rewrite it into a grpc-web response.
    assert not response.headers.get("content-type", "").lower().startswith(
        "application/grpc-web"
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("content_type", "text"),
    [
        ("application/grpc-web", False),
        ("application/grpc-web+proto", False),
        ("application/grpc-web-text", True),
        ("application/grpc-web-text+proto", True),
        ("application/grpc-web+proto; charset=utf-8", False),
        ("application/grpc-web-text+proto; charset=utf-8", True),
    ],
)
def test_nginx_accepts_only_supported_media_type_token_with_optional_parameters(
    content_type: str, text: bool
):
    assert_grpc_web_success(post_with_content_type(content_type, text=text))


@pytest.mark.integration
def test_oversized_native_frame_is_rejected_before_memory_amplification():
    before = nginx_rss_kb()

    # The M7 fault listener has grpc_web_max_frame_size 1k while the backend
    # advertises a 4096-byte native gRPC frame and sends no payload. Repeating
    # the attack proves the declared length is rejected before scratch growth.
    for _ in range(25):
        consume_fault("oversized-frame")

    time.sleep(0.2)
    after = nginx_rss_kb()

    assert after - before < 16 * 1024
    assert_main_path_still_healthy()


@pytest.mark.integration
def test_truncated_native_frame_does_not_poison_worker_state():
    for _ in range(10):
        consume_fault("truncated-frame")

    assert_main_path_still_healthy()


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["rst-after-data", "tcp-reset-after-data"])
def test_after_data_transport_fault_preserves_completed_data(mode: str):
    frames = observe_fault_frames(mode)
    expected = protobuf_string_field_1("before-transport-fault") + bytes([0x10, 0x01])

    assert frames[0].payload == expected
    assert_main_path_still_healthy()


@pytest.mark.integration
def test_missing_native_trailers_never_become_false_grpc_success():
    frames = observe_fault_frames("clean-without-trailers")
    expected = protobuf_string_field_1("before-transport-fault") + bytes([0x10, 0x01])

    assert frames[0].payload == expected
    for frame in frames[1:]:
        if frame.is_trailer:
            assert parse_trailers(frame.payload).get("grpc-status") != "0"

    assert_main_path_still_healthy()


@pytest.mark.integration
def test_repeated_after_data_transport_faults_do_not_accumulate_request_memory():
    before = nginx_rss_kb()

    for mode in ("rst-after-data", "tcp-reset-after-data"):
        for _ in range(8):
            frames = observe_fault_frames(mode)
            assert frames[0].payload.startswith(
                protobuf_string_field_1("before-transport-fault")
            )

    time.sleep(0.3)
    after = nginx_rss_kb()

    assert after - before < 16 * 1024
    assert_main_path_still_healthy()


@pytest.mark.integration
def test_repeated_downstream_disconnects_do_not_accumulate_request_memory():
    body = base64.b64encode(
        encode_data_frame(
            protobuf_string_field_1("cancel-stress")
            + bytes([0x10, 0x64, 0x18, 0x14])  # count=100, delay_ms=20
        )
    )
    before = nginx_rss_kb()

    for _ in range(30):
        try:
            with httpx.stream(
                "POST",
                f"{MODULE}/grpcwebtest.TestService/Stream",
                content=body,
                headers=text_headers(),
                timeout=3,
            ) as response:
                assert response.status_code == 200
                iterator = response.iter_raw()
                next(iterator, b"")
                # Exiting the context closes downstream while the native RPC
                # is still active, exercising request cleanup repeatedly.
        except httpx.HTTPError:
            pass

    time.sleep(0.3)
    after = nginx_rss_kb()

    assert after - before < 16 * 1024
    assert_main_path_still_healthy()


@pytest.mark.integration
def test_error_logs_do_not_leak_authorization_or_request_payload():
    secret = "m7-secret-do-not-log-8af0d5d7"

    response = httpx.post(
        f"{MODULE}/grpcwebtest.TestService/Unary",
        content=(b"%%%" + secret.encode()),
        headers=text_headers(authorization=f"Bearer {secret}"),
        timeout=5,
    )
    assert response.status_code == 400

    logs = subprocess.check_output(
        ["docker", "compose", "logs", "--no-color", "nginx"],
        text=True,
        timeout=10,
        stderr=subprocess.STDOUT,
    )
    assert secret not in logs
