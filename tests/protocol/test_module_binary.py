import os

import httpx
import pytest

from grpc_web import decode_frames, encode_data_frame, parse_trailers


REFERENCE = os.getenv("REFERENCE_URL", "http://127.0.0.1:18081")
MODULE = os.getenv("MODULE_URL", "http://127.0.0.1:18080")


def protobuf_string_field_1(value: str) -> bytes:
    raw = value.encode()
    if len(raw) >= 128:
        raise ValueError("fixture only supports short strings")
    return bytes([0x0A, len(raw)]) + raw


def call_binary_unary(url: str, message: str = "hello") -> tuple[httpx.Response, list]:
    request_frame = encode_data_frame(protobuf_string_field_1(message))
    response = httpx.post(
        f"{url}/grpcwebtest.TestService/Unary",
        content=request_frame,
        headers={
            "content-type": "application/grpc-web+proto",
            "x-grpc-web": "1",
            "accept": "application/grpc-web+proto",
        },
        timeout=5,
    )
    return response, decode_frames(response.content)


def canonical(response: httpx.Response, frames: list) -> tuple:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/grpc-web")
    assert len(frames) >= 2
    assert not frames[0].is_trailer
    assert frames[-1].is_trailer

    return (
        [frame.payload for frame in frames if not frame.is_trailer],
        parse_trailers(frames[-1].payload),
    )


@pytest.mark.integration
def test_nginx_binary_unary():
    response, frames = call_binary_unary(MODULE)
    data, trailers = canonical(response, frames)

    assert data == [b"\x0a\x05hello\x10\x01"]
    assert trailers["grpc-status"] == "0"
    assert trailers["x-test-trailer"] == "unary-ok"


@pytest.mark.integration
def test_nginx_binary_unary_matches_envoy():
    envoy = canonical(*call_binary_unary(REFERENCE))
    nginx = canonical(*call_binary_unary(MODULE))
    assert nginx == envoy
