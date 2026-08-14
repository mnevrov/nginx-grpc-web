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
    encoded = b"".join(chunks)
    raw = base64.b64decode(encoded, validate=True)
    return decode_frames(raw)


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
