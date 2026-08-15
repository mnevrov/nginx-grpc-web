#include <assert.h>
#include <stddef.h>
#include <stdint.h>

#include "../../src/grpc_web_frame.h"

int
LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    size_t n, off, chunk, before;
    grpc_web_frame_parser_t parser;

    grpc_web_frame_parser_init(&parser);
    off = 0;

    while (off < size) {
        chunk = 1 + ((data[off] + off) % 23);
        if (chunk > size - off) {
            chunk = size - off;
        }

        while (chunk != 0) {
            before = parser.payload_seen;
            n = grpc_web_frame_consume(&parser, data + off, chunk);

            assert(n <= chunk);
            assert(parser.header_len <= GRPC_WEB_FRAME_HEADER_SIZE);
            if (parser.header_ready) {
                assert(parser.payload_seen <= parser.length);
                assert(parser.payload_seen >= before);
            }

            off += n;
            chunk -= n;

            if (!grpc_web_frame_is_complete(&parser)) {
                if (n == 0) {
                    return 0;
                }
                continue;
            }

            grpc_web_frame_next(&parser);
        }
    }

    assert(parser.header_len <= GRPC_WEB_FRAME_HEADER_SIZE);
    if (parser.header_ready) {
        assert(parser.payload_seen <= parser.length);
    }

    return 0;
}
