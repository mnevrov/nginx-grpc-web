#include "grpc_web_frame.h"

#include <string.h>

void
grpc_web_frame_parser_init(grpc_web_frame_parser_t *p)
{
    memset(p, 0, sizeof(*p));
}

size_t
grpc_web_frame_consume(grpc_web_frame_parser_t *p,
    const uint8_t *src, size_t src_len)
{
    size_t n, need;
    uint32_t remaining;

    if (!p->header_ready) {
        need = GRPC_WEB_FRAME_HEADER_SIZE - p->header_len;
        n = src_len < need ? src_len : need;

        if (n != 0) {
            memcpy(p->header + p->header_len, src, n);
            p->header_len += n;
        }

        if (p->header_len == GRPC_WEB_FRAME_HEADER_SIZE) {
            p->flags = p->header[0];
            p->length = ((uint32_t) p->header[1] << 24)
                      | ((uint32_t) p->header[2] << 16)
                      | ((uint32_t) p->header[3] << 8)
                      | ((uint32_t) p->header[4]);
            p->header_ready = 1;
        }

        return n;
    }

    remaining = p->length - p->payload_seen;
    n = src_len < remaining ? src_len : remaining;
    p->payload_seen += (uint32_t) n;
    return n;
}

int
grpc_web_frame_is_complete(const grpc_web_frame_parser_t *p)
{
    return p->header_ready && p->payload_seen == p->length;
}

void
grpc_web_frame_next(grpc_web_frame_parser_t *p)
{
    memset(p, 0, sizeof(*p));
}
