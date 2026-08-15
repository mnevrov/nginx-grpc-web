from __future__ import annotations

import base64
import dataclasses
import struct
from typing import Iterable


@dataclasses.dataclass(frozen=True)
class Frame:
    flags: int
    payload: bytes

    @property
    def is_trailer(self) -> bool:
        return bool(self.flags & 0x80)


def encode_data_frame(payload: bytes, flags: int = 0) -> bytes:
    return bytes([flags]) + struct.pack(">I", len(payload)) + payload


def decode_frames(raw: bytes) -> list[Frame]:
    out: list[Frame] = []
    pos = 0

    while pos < len(raw):
        if len(raw) - pos < 5:
            raise ValueError("incomplete grpc-web frame header")

        flags = raw[pos]
        length = struct.unpack(">I", raw[pos + 1 : pos + 5])[0]
        pos += 5

        if len(raw) - pos < length:
            raise ValueError("incomplete grpc-web frame payload")

        out.append(Frame(flags=flags, payload=raw[pos : pos + length]))
        pos += length

    return out


def decode_text_body(chunks: Iterable[bytes]) -> list[Frame]:
    """Decode gRPC-Web text across arbitrary HTTP transport chunks.

    A response is not necessarily one Base64 document. Proxies such as Envoy
    may encode complete gRPC frames independently, so valid padding (``=``)
    can occur before later encoded frames. Decode strict Base64 quartets
    incrementally instead of concatenating the body into one b64decode call.
    """
    raw = bytearray()
    quartet = bytearray()

    for chunk in chunks:
        for value in chunk:
            quartet.append(value)
            if len(quartet) == 4:
                raw.extend(base64.b64decode(bytes(quartet), validate=True))
                quartet.clear()

    if quartet:
        raise ValueError("incomplete grpc-web-text base64 quartet")

    return decode_frames(bytes(raw))


def parse_trailers(payload: bytes) -> dict[str, str]:
    text = payload.decode("ascii")
    result: dict[str, str] = {}

    for line in text.split("\r\n"):
        if not line:
            continue
        name, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"invalid trailer line: {line!r}")
        result[name.lower()] = value

    return result
