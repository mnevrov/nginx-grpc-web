import base64

from grpc_web import decode_frames, decode_text_body, encode_data_frame, parse_trailers


def test_decode_one_data_frame():
    raw = encode_data_frame(b"abc")
    frames = decode_frames(raw)
    assert len(frames) == 1
    assert frames[0].flags == 0
    assert frames[0].payload == b"abc"


def test_decode_text_across_arbitrary_chunks():
    encoded = base64.b64encode(encode_data_frame(b"abc"))
    chunks = [encoded[:1], encoded[1:3], encoded[3:7], encoded[7:]]
    frames = decode_text_body(chunks)
    assert frames[0].payload == b"abc"


def test_parse_trailers():
    trailers = parse_trailers(b"grpc-status:0\r\nx-test:yes\r\n")
    assert trailers == {"grpc-status": "0", "x-test": "yes"}
