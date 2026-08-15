import base64
import os

import httpx
import pytest

from grpc_web import decode_frames, decode_text_body, encode_data_frame, parse_trailers


MODULE = os.getenv("MODULE_URL", "http://127.0.0.1:18080")


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
