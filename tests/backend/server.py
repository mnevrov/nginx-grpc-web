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


class TestService(test_pb2_grpc.TestServiceServicer):
    async def Unary(self, request, context):
        context.set_trailing_metadata((("x-test-trailer", "unary-ok"),))
        return test_pb2.EchoReply(message=request.message, sequence=1)

    async def Stream(self, request, context):
        count = request.count or 3
        delay = (request.delay_ms or 250) / 1000.0

        context.set_trailing_metadata((("x-test-trailer", "stream-ok"),))

        for i in range(count):
            if context.cancelled():
                return
            await asyncio.sleep(delay)
            yield test_pb2.EchoReply(
                message=request.message,
                sequence=i + 1,
            )

    async def Fail(self, request, context):
        mapping = {
            3: grpc.StatusCode.INVALID_ARGUMENT,
            5: grpc.StatusCode.NOT_FOUND,
            13: grpc.StatusCode.INTERNAL,
        }
        code = mapping.get(request.code, grpc.StatusCode.UNKNOWN)
        await context.abort(code, request.message or "forced failure")


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
