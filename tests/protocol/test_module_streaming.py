import base64
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx
import pytest

from grpc_web import Frame, encode_data_frame, iter_text_frames, parse_trailers


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


def stream_request(message: str, count: int, delay_ms: int) -> bytes:
    return (
        protobuf_string_field(1, message)
        + bytes([0x10])
        + varint(count)
        + bytes([0x18])
        + varint(delay_ms)
    )


def expected_reply(message: str, sequence: int) -> bytes:
    return protobuf_string_field(1, message) + bytes([0x10]) + varint(sequence)


def text_headers() -> dict[str, str]:
    return {
        "content-type": "application/grpc-web-text+proto",
        "x-grpc-web": "1",
        "accept": "application/grpc-web-text+proto",
    }


@dataclass
class StreamObservation:
    headers: dict[str, str]
    frames: list[Frame]
    arrivals: list[float]
    finished: float

    @property
    def data_frames(self) -> list[Frame]:
        return [frame for frame in self.frames if not frame.is_trailer]

    @property
    def data_arrivals(self) -> list[float]:
        return [
            arrival
            for frame, arrival in zip(self.frames, self.arrivals)
            if not frame.is_trailer
        ]

    @property
    def trailers(self) -> dict[str, str]:
        assert self.frames and self.frames[-1].is_trailer
        return parse_trailers(self.frames[-1].payload)


def observe_text_stream(
    url: str,
    *,
    message: str = "stream",
    count: int = 3,
    delay_ms: int = 250,
    consumer_delay_ms: int = 0,
    timeout: float = 10,
) -> StreamObservation:
    payload = stream_request(message, count, delay_ms)
    encoded = base64.b64encode(encode_data_frame(payload))

    started = time.monotonic()
    frames: list[Frame] = []
    arrivals: list[float] = []

    with httpx.stream(
        "POST",
        f"{url}/grpcwebtest.TestService/Stream",
        content=encoded,
        headers=text_headers(),
        timeout=timeout,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            "application/grpc-web-text+proto"
        )
        headers = dict(response.headers)

        for frame in iter_text_frames(response.iter_raw()):
            frames.append(frame)
            arrivals.append(time.monotonic() - started)
            if consumer_delay_ms:
                time.sleep(consumer_delay_ms / 1000.0)

    return StreamObservation(
        headers=headers,
        frames=frames,
        arrivals=arrivals,
        finished=time.monotonic() - started,
    )


def nginx_rss_kb() -> int:
    """Return aggregate RSS of NGINX master/workers inside the test container."""
    script = r'''
awk '
  /^Name:/ { is_nginx = ($2 == "nginx") }
  /^VmRSS:/ && is_nginx { sum += $2 }
  END { print sum + 0 }
' /proc/[0-9]*/status 2>/dev/null
'''
    raw = subprocess.check_output(
        ["docker", "compose", "exec", "-T", "nginx", "sh", "-c", script],
        text=True,
        timeout=5,
    )
    return int(raw.strip())


def assert_incremental(
    observation: StreamObservation,
    *,
    count: int,
    delay_ms: int,
) -> None:
    assert len(observation.data_frames) == count
    assert observation.frames[-1].is_trailer
    assert observation.trailers["grpc-status"] == "0"
    assert observation.trailers["x-test-trailer"] == "stream-ok"

    times = observation.data_arrivals
    assert len(times) == count

    delay = delay_ms / 1000.0

    # Whole-stream buffering would collapse these gaps to approximately zero.
    for earlier, later in zip(times, times[1:]):
        assert later - earlier >= delay * 0.35

    # The first DATA frame must be observable well before the RPC completes.
    assert observation.finished - times[0] >= delay * 0.70

    # Keep a bounded sanity check so pathological proxy stalls are visible.
    assert times[-1] - times[0] <= delay * (count - 1) * 4 + 1.0


def canonical(observation: StreamObservation) -> tuple[list[bytes], dict[str, str]]:
    return [frame.payload for frame in observation.data_frames], observation.trailers


@pytest.mark.integration
def test_nginx_text_server_stream_is_incremental():
    count = 3
    delay_ms = 250
    message = "nginx-stream"

    observation = observe_text_stream(
        MODULE,
        message=message,
        count=count,
        delay_ms=delay_ms,
    )

    assert_incremental(observation, count=count, delay_ms=delay_ms)
    assert [frame.payload for frame in observation.data_frames] == [
        expected_reply(message, sequence) for sequence in range(1, count + 1)
    ]


@pytest.mark.integration
def test_nginx_text_server_stream_matches_envoy_semantics_and_timing():
    count = 3
    delay_ms = 250
    message = "diff-stream"

    envoy = observe_text_stream(
        REFERENCE,
        message=message,
        count=count,
        delay_ms=delay_ms,
    )
    nginx = observe_text_stream(
        MODULE,
        message=message,
        count=count,
        delay_ms=delay_ms,
    )

    assert_incremental(envoy, count=count, delay_ms=delay_ms)
    assert_incremental(nginx, count=count, delay_ms=delay_ms)
    assert canonical(nginx) == canonical(envoy)

    envoy_span = envoy.data_arrivals[-1] - envoy.data_arrivals[0]
    nginx_span = nginx.data_arrivals[-1] - nginx.data_arrivals[0]

    # Compare timing shape, not exact scheduler-dependent timestamps.
    assert nginx_span >= envoy_span * 0.45
    assert nginx_span <= envoy_span * 2.5 + 0.25


@pytest.mark.integration
def test_nginx_text_server_stream_large_frames_are_not_whole_stream_buffered():
    count = 2
    delay_ms = 250
    message = "large-stream-" + ("x" * 8192)

    observation = observe_text_stream(
        MODULE,
        message=message,
        count=count,
        delay_ms=delay_ms,
    )

    assert_incremental(observation, count=count, delay_ms=delay_ms)
    assert [frame.payload for frame in observation.data_frames] == [
        expected_reply(message, sequence) for sequence in range(1, count + 1)
    ]


@pytest.mark.integration
def test_nginx_text_server_stream_survives_slow_consumer_backpressure():
    count = 96
    message = "slow-consumer-" + ("s" * 32768)

    observation = observe_text_stream(
        MODULE,
        message=message,
        count=count,
        delay_ms=1,
        consumer_delay_ms=15,
        timeout=20,
    )

    assert len(observation.data_frames) == count
    assert observation.frames[-1].is_trailer
    assert observation.trailers["grpc-status"] == "0"
    assert observation.trailers["x-test-trailer"] == "stream-ok"
    assert observation.data_frames[0].payload == expected_reply(message, 1)
    assert observation.data_frames[-1].payload == expected_reply(message, count)


@pytest.mark.integration
def test_nginx_long_stream_does_not_retain_every_encoded_frame():
    # Each response message is ~64 KiB; 480 frames are >30 MiB of native
    # payload and >40 MiB after Base64. A per-frame request-pool allocation
    # strategy retains far more than the allowed RSS delta until stream end.
    count = 480
    message = "rss-" + ("m" * 65536)
    baseline = nginx_rss_kb()
    samples = [baseline]

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            observe_text_stream,
            MODULE,
            message=message,
            count=count,
            delay_ms=4,
            timeout=30,
        )

        while not future.done():
            time.sleep(0.15)
            samples.append(nginx_rss_kb())

        observation = future.result()

    assert len(observation.data_frames) == count
    assert observation.trailers["grpc-status"] == "0"

    peak_delta_kb = max(samples) - baseline
    # Generous CI allowance. A streaming filter should keep working memory
    # bounded to in-flight/current frames rather than total bytes streamed.
    assert peak_delta_kb < 32 * 1024, (
        f"NGINX RSS grew by {peak_delta_kb / 1024:.1f} MiB during long stream"
    )
