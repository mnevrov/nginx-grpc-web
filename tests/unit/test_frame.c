#include <assert.h>
#include <stdint.h>
#include <stdio.h>

#include "../../src/grpc_web_frame.h"

static void
test_parser(void)
{
    grpc_web_frame_parser_t p;
    uint8_t frame[] = {0x00, 0x00, 0x00, 0x00, 0x03, 'a', 'b', 'c'};
    size_t n;

    grpc_web_frame_parser_init(&p);

    n = grpc_web_frame_consume(&p, frame, 2);
    assert(n == 2);
    assert(!p.header_ready);

    n = grpc_web_frame_consume(&p, frame + 2, 3);
    assert(n == 3);
    assert(p.header_ready);
    assert(p.length == 3);

    n = grpc_web_frame_consume(&p, frame + 5, 1);
    assert(n == 1);
    assert(!grpc_web_frame_is_complete(&p));

    n = grpc_web_frame_consume(&p, frame + 6, 2);
    assert(n == 2);
    assert(grpc_web_frame_is_complete(&p));
}

static void
test_trailer_header_writer(void)
{
    uint8_t header[GRPC_WEB_FRAME_HEADER_SIZE];

    grpc_web_frame_write_header(header, GRPC_WEB_TRAILER_FLAG, 0x01020304u);

    assert(header[0] == 0x80);
    assert(header[1] == 0x01);
    assert(header[2] == 0x02);
    assert(header[3] == 0x03);
    assert(header[4] == 0x04);
}

int
main(void)
{
    test_parser();
    test_trailer_header_writer();
    puts("frame tests: ok");
    return 0;
}
