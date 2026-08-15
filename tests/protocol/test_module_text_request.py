import base64
import os
from collections.abc import Iterable

import httpx
import pytest

from grpc_web import decode_frames, decode_text_body, encode_data_frame


REFERENCE = os.getenv("REFERENCE_URL", "http://127.0.0.1:18081")
MODULE = os.getenv("MODULE_URL", "http://127.0.0.1:18080")


def protobuf_string_field_1(value: str) -> bytes:
    raw = value.encode()
    if len(raw) >= 128:
        raise ValueError("fixture only supports short strings")
    return bytes([0x0A, len(raw)]) + raw


def encoded_unary_request(message: str = "hello") -> bytes:
    frame = encode_data_frame(protobuf_string_field_1(message))
    return base64.b64encode(frame)


def text_headers() -> dict[str, str]:
    return {
        "content-type": "application/grpc-web-text+proto",
        "x-grpc-web": "1",
        "accept": "application/grpc-web-text+proto",
    }


def decoded_data_payloads(response: httpx.Response) -> list[bytes]:
    content_type = response.headers.get("content-type", "").lower()
    if content_type.startswith("application/grpc-web-text"):
        frames = decode_text_body([response.content])
    else:
        # M3 deliberately tests only the request path. Until M4, NGINX returns
        # the backend native gRPC DATA body for text-mode requests.
        frames = decode_frames(response.content)

    return [frame.payload for frame in frames if not frame.is_trailer]


def fragmented(data: bytes, pattern: tuple[int, ...]) -> Iterable[bytes]:
    pos = 0
    i = 0
    while pos < len(data):
        size = pattern[i % len(pattern)]
        yield data[pos : pos + size]
        pos += size
        i += 1


def post_text(url: str, content) -> httpx.Response:
    return httpx.post(
        f"{url}/grpcwebtest.TestService/Unary",
        content=content,
        headers=text_headers(),
        timeout=5,
    )


@pytest.mark.integration
def test_nginx_text_unary_fixed_content_length_decodes_request():
    encoded = encoded_unary_request("hello")
    response = post_text(MODULE, encoded)

    assert response.status_code == 200
    assert decoded_data_payloads(response) == [b"\x0a\x05hello\x10\x01"]


@pytest.mark.integration
@pytest.mark.parametrize(
    "pattern",
    [
        (1,),
        (1, 3),
        (2, 2),
        (3, 1),
        (1, 2, 3, 4),
    ],
)
def test_nginx_text_unary_chunked_fragmentation(pattern):
    encoded = encoded_unary_request("hello")
    response = post_text(MODULE, fragmented(encoded, pattern))

    assert response.status_code == 200
    assert decoded_data_payloads(response) == [b"\x0a\x05hello\x10\x01"]


@pytest.mark.integration
def test_nginx_text_request_semantics_match_envoy():
    encoded = encoded_unary_request("hello")

    envoy = post_text(REFERENCE, encoded)
    nginx = post_text(MODULE, encoded)

    assert envoy.status_code == 200
    assert nginx.status_code == 200
    assert decoded_data_payloads(nginx) == decoded_data_payloads(envoy)


@pytest.mark.integration
@pytest.mark.parametrize("body", [b"!!!!", b"AAAAA", b"Zg==AAAA"])
def test_nginx_rejects_malformed_text_request(body):
    response = post_text(MODULE, body)
    assert response.status_code == 400
