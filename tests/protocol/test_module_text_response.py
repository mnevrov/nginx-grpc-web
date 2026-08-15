import base64
import os

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


def protobuf_string_field(field_number: int, value: str) -> bytes:
    raw = value.encode()
    return bytes([(field_number << 3) | 2]) + varint(len(raw)) + raw


def text_headers() -> dict[str, str]:
    return {
        "content-type": "application/grpc-web-text+proto",
        "x-grpc-web": "1",
        "accept": "application/grpc-web-text+proto",
    }


def call_text_unary(url: str, message: str = "hello") -> tuple[httpx.Response, list]:
    request = protobuf_string_field(1, message)
    response = httpx.post(
        f"{url}/grpcwebtest.TestService/Unary",
        content=base64.b64encode(encode_data_frame(request)),
        headers=text_headers(),
        timeout=10,
    )
    return response, decode_text_body(response.iter_bytes())


def call_text_fail(
    url: str, code: int = 3, message: str = "forced failure"
) -> tuple[httpx.Response, list]:
    request = bytes([0x08]) + varint(code) + protobuf_string_field(2, message)
    response = httpx.post(
        f"{url}/grpcwebtest.TestService/Fail",
        content=base64.b64encode(encode_data_frame(request)),
        headers=text_headers(),
        timeout=10,
    )
    return response, decode_text_body(response.iter_bytes())


def canonical(response: httpx.Response, frames: list) -> tuple[list[bytes], dict[str, str]]:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/grpc-web-text+proto"
    )

    data = [frame.payload for frame in frames if not frame.is_trailer]
    trailers: dict[str, str] = {}

    if frames and frames[-1].is_trailer:
        trailers.update(parse_trailers(frames[-1].payload))

    # A trailers-only gRPC response may surface grpc-status/grpc-message as
    # response headers rather than as a grpc-web body trailer frame. That is
    # wire-shape variance, not an observable RPC semantic difference.
    for key in ("grpc-status", "grpc-message", "x-test-trailer"):
        if key in response.headers and key not in trailers:
            trailers[key] = response.headers[key]

    return data, trailers


def canonical_success(response: httpx.Response, frames: list) -> tuple[list[bytes], dict[str, str]]:
    assert frames
    assert frames[-1].is_trailer
    return canonical(response, frames)


@pytest.mark.integration
def test_nginx_text_unary_response():
    data, trailers = canonical_success(*call_text_unary(MODULE))

    assert data == [b"\x0a\x05hello\x10\x01"]
    assert trailers["grpc-status"] == "0"
    assert trailers["x-test-trailer"] == "unary-ok"


@pytest.mark.integration
def test_nginx_text_unary_response_matches_envoy():
    envoy = canonical_success(*call_text_unary(REFERENCE))
    nginx = canonical_success(*call_text_unary(MODULE))
    assert nginx == envoy


@pytest.mark.integration
def test_nginx_text_response_fragmented_native_frame_matches_envoy():
    # Larger than the NGINX test grpc_buffer_size so one native gRPC frame is
    # necessarily split across upstream buffers before the module sees it.
    message = "fragment-me-" + ("x" * 8192)

    envoy = canonical_success(*call_text_unary(REFERENCE, message))
    nginx = canonical_success(*call_text_unary(MODULE, message))
    assert nginx == envoy


@pytest.mark.integration
def test_nginx_text_nonzero_status_and_message_match_envoy():
    envoy_data, envoy_trailers = canonical(
        *call_text_fail(REFERENCE, 3, "bad request from browser")
    )
    nginx_data, nginx_trailers = canonical(
        *call_text_fail(MODULE, 3, "bad request from browser")
    )

    assert nginx_data == envoy_data == []
    assert nginx_trailers == envoy_trailers
    assert nginx_trailers["grpc-status"] == "3"
    assert "grpc-message" in nginx_trailers
