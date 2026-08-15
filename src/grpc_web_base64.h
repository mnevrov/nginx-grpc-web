#ifndef _GRPC_WEB_BASE64_H_INCLUDED_
#define _GRPC_WEB_BASE64_H_INCLUDED_

#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint8_t pending[4];
    size_t pending_len;
    unsigned finished:1;
} grpc_web_b64_decoder_t;

typedef struct {
    uint8_t pending[3];
    size_t pending_len;
} grpc_web_b64_encoder_t;

void grpc_web_b64_decoder_init(grpc_web_b64_decoder_t *st);
void grpc_web_b64_encoder_init(grpc_web_b64_encoder_t *st);

/*
 * Bootstrap API. Implementation is intentionally isolated from NGINX so it can
 * be unit-tested and fuzzed independently.
 *
 * Return values:
 *   0  success
 *  -1  malformed input
 *  -2  output buffer too small
 */
int grpc_web_b64_decode_update(grpc_web_b64_decoder_t *st,
    const uint8_t *src, size_t src_len, uint8_t *dst, size_t dst_cap,
    size_t *written, int final);

int grpc_web_b64_encode_update(grpc_web_b64_encoder_t *st,
    const uint8_t *src, size_t src_len, uint8_t *dst, size_t dst_cap,
    size_t *written, int final);

#endif
