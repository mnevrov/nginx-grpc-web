#include <assert.h>
#include <stdint.h>
#include <stdio.h>

#include "../../src/grpc_web_frame.h"

int
main(void)
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

    puts("frame tests: ok");
    return 0;
}
