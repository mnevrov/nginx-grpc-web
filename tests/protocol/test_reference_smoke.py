import base64
import os
import time

import httpx
import pytest

from grpc_web import decode_text_body, encode_data_frame, parse_trailers


REFERENCE = os.getenv("REFERENCE_URL", "http://127.0.0.1:18081")


def protobuf_string_field_1(value: str) -> bytes:
    raw = value.encode()
    if len(raw) >= 128:
        raise ValueError("fixture only supports short strings")
    return bytes([0x0A, len(raw)]) + raw


@pytest.mark.integration
def test_envoy_unary_text_reference():
    # EchoRequest { message: "hello" }
    request_frame = encode_data_frame(protobuf_string_field_1("hello"))
    body = base64.b64encode(request_frame)

    response = httpx.post(
        f"{REFERENCE}/grpcwebtest.TestService/Unary",
        content=body,
        headers={
            "content-type": "application/grpc-web-text+proto",
            "x-grpc-web": "1",
            "accept": "application/grpc-web-text",
        },
        timeout=5,
    )

    assert response.status_code == 200
    frames = decode_text_body([response.content])

    assert len(frames) >= 2
    assert not frames[0].is_trailer
    assert frames[-1].is_trailer

    trailers = parse_trailers(frames[-1].payload)
    assert trailers["grpc-status"] == "0"
    assert trailers["x-test-trailer"] == "unary-ok"
