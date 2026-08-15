import base64
import os
import subprocess
import time

import httpx
import pytest

from grpc_web import decode_text_body, encode_data_frame, parse_trailers


REFERENCE = os.getenv("REFERENCE_URL", "http://127.0.0.1:18081")
MODULE = os.getenv("MODULE_URL", "http://127.0.0.1:18080")


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def string_field(field_number: int, value: str) -> bytes:
    raw = value.encode()
    return bytes([(field_number << 3) | 2]) + varint(len(raw)) + raw


def uint_field(field_number: int, value: int) -> bytes:
    return bytes([(field_number << 3) | 0]) + varint(value)


def stream_request(
    *,
    message: str,
    count: int = 3,
    delay_ms: int = 250,
    empty: bool = False,
    fail_after: int = 0,
    fail_code: int = 0,
    fail_message: str = "",
) -> bytes:
    out = bytearray()
    if message:
        out += string_field(1, message)
    if count:
        out += uint_field(2, count)
    if delay_ms:
        out += uint_field(3, delay_ms)
    if empty:
        out += uint_field(4, 1)
    if fail_after:
        out += uint_field(5, fail_after)
    if fail_code:
        out += uint_field(6, fail_code)
    if fail_message:
        out += string_field(7, fail_message)
    return bytes(out)


def text_headers(**extra: str) -> dict[str, str]:
    headers = {
        "content-type": "application/grpc-web-text+proto",
        "x-grpc-web": "1",
        "accept": "application/grpc-web-text+proto",
    }
    headers.update(extra)
    return headers


def call_stream(url: str, payload: bytes, **headers: str):
    response = httpx.post(
        f"{url}/grpcwebtest.TestService/Stream",
        content=base64.b64encode(encode_data_frame(payload)),
        headers=text_headers(**headers),
        timeout=10,
    )
    frames = decode_text_body(response.iter_bytes())
    return response, frames


def canonical(response: httpx.Response, frames: list):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/grpc-web-text+proto"
    )

    data = [frame.payload for frame in frames if not frame.is_trailer]
    trailers = {}
    if frames and frames[-1].is_trailer:
        trailers.update(parse_trailers(frames[-1].payload))

    for key in ("grpc-status", "grpc-message", "x-test-trailer"):
        if key in response.headers and key not in trailers:
            trailers[key] = response.headers[key]

    return data, trailers


def backend_logs() -> str:
    return subprocess.check_output(
        ["docker", "compose", "logs", "--no-color", "backend"],
        text=True,
        timeout=5,
    )


@pytest.mark.integration
def test_nginx_empty_stream_matches_envoy():
    payload = stream_request(message="empty", empty=True)
    envoy = canonical(*call_stream(REFERENCE, payload))
    nginx = canonical(*call_stream(MODULE, payload))

    assert nginx == envoy
    data, trailers = nginx
    assert data == []
    assert trailers["grpc-status"] == "0"
    assert trailers["x-test-trailer"] == "stream-empty"


@pytest.mark.integration
def test_nginx_midstream_failure_matches_envoy():
    payload = stream_request(
        message="before-failure",
        count=4,
        delay_ms=50,
        fail_after=1,
        fail_code=13,
        fail_message="midstream protocol failure",
    )
    envoy = canonical(*call_stream(REFERENCE, payload))
    nginx = canonical(*call_stream(MODULE, payload))

    assert nginx == envoy
    data, trailers = nginx
    assert len(data) == 1
    assert trailers["grpc-status"] == "13"
    assert "grpc-message" in trailers
    assert trailers["x-test-trailer"] == "stream-fail"


@pytest.mark.integration
def test_nginx_grpc_timeout_matches_envoy():
    payload = stream_request(
        message="deadline",
        count=3,
        delay_ms=500,
    )
    envoy = canonical(*call_stream(REFERENCE, payload, **{"grpc-timeout": "150m"}))
    nginx = canonical(*call_stream(MODULE, payload, **{"grpc-timeout": "150m"}))

    assert nginx == envoy
    data, trailers = nginx
    assert data == []
    assert trailers["grpc-status"] == "4"


@pytest.mark.integration
def test_nginx_client_disconnect_cancels_upstream():
    marker = f"cancel-protocol-{time.time_ns()}"
    payload = stream_request(
        message=marker,
        count=50,
        delay_ms=40,
    )
    encoded = base64.b64encode(encode_data_frame(payload))

    with httpx.stream(
        "POST",
        f"{MODULE}/grpcwebtest.TestService/Stream",
        content=encoded,
        headers=text_headers(),
        timeout=5,
    ) as response:
        assert response.status_code == 200
        iterator = response.iter_raw()
        first = next(iterator)
        assert first
        # Closing the downstream response must propagate cancellation upstream.

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if f"stream cancelled message={marker}" in backend_logs():
            break
        time.sleep(0.1)
    else:
        pytest.fail("backend did not observe cancellation after downstream close")
