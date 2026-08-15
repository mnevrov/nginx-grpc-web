#ifndef _GRPC_WEB_FRAME_H_INCLUDED_
#define _GRPC_WEB_FRAME_H_INCLUDED_

#include <stddef.h>
#include <stdint.h>

#define GRPC_WEB_FRAME_HEADER_SIZE 5
#define GRPC_WEB_TRAILER_FLAG 0x80u

typedef struct {
    uint8_t header[GRPC_WEB_FRAME_HEADER_SIZE];
    size_t header_len;
    uint8_t flags;
    uint32_t length;
    uint32_t payload_seen;
    unsigned header_ready:1;
} grpc_web_frame_parser_t;

void grpc_web_frame_parser_init(grpc_web_frame_parser_t *p);

void grpc_web_frame_write_header(uint8_t out[GRPC_WEB_FRAME_HEADER_SIZE],
    uint8_t flags, uint32_t length);

/*
 * Consume only enough bytes to complete the current frame header/payload.
 * The caller owns buffering/forwarding of payload bytes.
 */
size_t grpc_web_frame_consume(grpc_web_frame_parser_t *p,
    const uint8_t *src, size_t src_len);

int grpc_web_frame_is_complete(const grpc_web_frame_parser_t *p);
void grpc_web_frame_next(grpc_web_frame_parser_t *p);

#endif
