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


def test_decode_text_allows_padding_between_independently_encoded_frames():
    data = base64.b64encode(encode_data_frame(b"abc"))
    trailers = base64.b64encode(
        encode_data_frame(b"grpc-status:0\r\n", flags=0x80)
    )

    encoded = data + trailers
    chunks = [encoded[:5], encoded[5:11], encoded[11:19], encoded[19:]]
    frames = decode_text_body(chunks)

    assert [frame.payload for frame in frames] == [
        b"abc",
        b"grpc-status:0\r\n",
    ]
    assert frames[1].is_trailer


def test_parse_trailers():
    trailers = parse_trailers(b"grpc-status:0\r\nx-test:yes\r\n")
    assert trailers == {"grpc-status": "0", "x-test": "yes"}
