import asyncio
import os
import sys
from pathlib import Path

import grpc

HERE = Path(__file__).resolve().parent
GEN = HERE / "gen"
sys.path.insert(0, str(GEN))

import test_pb2  # noqa: E402
import test_pb2_grpc  # noqa: E402


def status_code(value: int) -> grpc.StatusCode:
    mapping = {
        3: grpc.StatusCode.INVALID_ARGUMENT,
        4: grpc.StatusCode.DEADLINE_EXCEEDED,
        5: grpc.StatusCode.NOT_FOUND,
        13: grpc.StatusCode.INTERNAL,
        14: grpc.StatusCode.UNAVAILABLE,
    }
    return mapping.get(value, grpc.StatusCode.UNKNOWN)


class TestService(test_pb2_grpc.TestServiceServicer):
    async def Unary(self, request, context):
        context.set_trailing_metadata((("x-test-trailer", "unary-ok"),))
        return test_pb2.EchoReply(message=request.message, sequence=1)

    async def Stream(self, request, context):
        if request.empty:
            context.set_trailing_metadata((("x-test-trailer", "stream-empty"),))
            return

        count = request.count or 3
        delay = (request.delay_ms or 250) / 1000.0

        context.set_trailing_metadata((("x-test-trailer", "stream-ok"),))

        try:
            for i in range(count):
                if context.cancelled():
                    print(f"stream cancelled message={request.message}", flush=True)
                    return

                await asyncio.sleep(delay)
                yield test_pb2.EchoReply(
                    message=request.message,
                    sequence=i + 1,
                )

                if request.fail_after and i + 1 >= request.fail_after:
                    context.set_trailing_metadata((("x-test-trailer", "stream-fail"),))
                    await context.abort(
                        status_code(request.fail_code or 13),
                        request.fail_message or "forced stream failure",
                    )
        except asyncio.CancelledError:
            print(f"stream cancelled message={request.message}", flush=True)
            raise

    async def Fail(self, request, context):
        await context.abort(
            status_code(request.code),
            request.message or "forced failure",
        )


async def main():
    port = int(os.getenv("PORT", "50051"))
    server = grpc.aio.server()
    test_pb2_grpc.add_TestServiceServicer_to_server(TestService(), server)
    server.add_insecure_port(f"0.0.0.0:{port}")
    await server.start()
    print(f"test backend listening on :{port}", flush=True)
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(main())
