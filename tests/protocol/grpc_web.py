from __future__ import annotations

import base64
import dataclasses
import struct
from typing import Iterable, Iterator


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


def iter_text_frames(chunks: Iterable[bytes]) -> Iterator[Frame]:
    """Yield gRPC-Web text frames as soon as transport bytes complete them.

    gRPC-Web text is allowed to cross arbitrary HTTP chunk boundaries. Envoy
    also Base64-encodes complete gRPC frames independently, so padding may
    legally appear before the next encoded frame. Decode strict quartets
    incrementally and keep only the currently incomplete decoded frame.
    """
    quartet = bytearray()
    raw = bytearray()

    for chunk in chunks:
        for value in chunk:
            quartet.append(value)
            if len(quartet) != 4:
                continue

            raw.extend(base64.b64decode(bytes(quartet), validate=True))
            quartet.clear()

            while True:
                if len(raw) < 5:
                    break

                length = struct.unpack(">I", raw[1:5])[0]
                frame_size = 5 + length
                if len(raw) < frame_size:
                    break

                yield Frame(flags=raw[0], payload=bytes(raw[5:frame_size]))
                del raw[:frame_size]

    if quartet:
        raise ValueError("incomplete grpc-web-text base64 quartet")

    if raw:
        if len(raw) < 5:
            raise ValueError("incomplete grpc-web frame header")
        raise ValueError("incomplete grpc-web frame payload")


def decode_text_body(chunks: Iterable[bytes]) -> list[Frame]:
    """Decode a complete gRPC-Web text body across arbitrary HTTP chunks."""
    return list(iter_text_frames(chunks))


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
