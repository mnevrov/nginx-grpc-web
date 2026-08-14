#include "grpc_web_base64.h"

#include <string.h>

/*
 * This file intentionally starts with a small, independent implementation
 * surface. Agents should complete it under tests before wiring text mode into
 * NGINX. See prompts/02_IMPLEMENT_REQUEST_PATH.md.
 */

static const uint8_t grpc_web_b64_table[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static int
grpc_web_b64_value(uint8_t c)
{
    if (c >= 'A' && c <= 'Z') return (int) (c - 'A');
    if (c >= 'a' && c <= 'z') return (int) (c - 'a') + 26;
    if (c >= '0' && c <= '9') return (int) (c - '0') + 52;
    if (c == '+') return 62;
    if (c == '/') return 63;
    if (c == '=') return -2;
    return -1;
}

void
grpc_web_b64_decoder_init(grpc_web_b64_decoder_t *st)
{
    memset(st, 0, sizeof(*st));
}

void
grpc_web_b64_encoder_init(grpc_web_b64_encoder_t *st)
{
    memset(st, 0, sizeof(*st));
}

static int
grpc_web_b64_decode_quartet(const uint8_t q[4], uint8_t *dst,
    size_t dst_cap, size_t *n)
{
    int a, b, c, d;

    a = grpc_web_b64_value(q[0]);
    b = grpc_web_b64_value(q[1]);
    c = grpc_web_b64_value(q[2]);
    d = grpc_web_b64_value(q[3]);

    if (a < 0 || b < 0 || c == -1 || d == -1) return -1;
    if (c == -2 && d != -2) return -1;

    if (dst_cap < 1) return -2;
    dst[0] = (uint8_t) ((a << 2) | (b >> 4));
    *n = 1;

    if (c == -2) return 0;

    if (dst_cap < 2) return -2;
    dst[1] = (uint8_t) (((b & 0x0f) << 4) | (c >> 2));
    *n = 2;

    if (d == -2) return 0;

    if (dst_cap < 3) return -2;
    dst[2] = (uint8_t) (((c & 0x03) << 6) | d);
    *n = 3;
    return 0;
}

int
grpc_web_b64_decode_update(grpc_web_b64_decoder_t *st,
    const uint8_t *src, size_t src_len, uint8_t *dst, size_t dst_cap,
    size_t *written, int final)
{
    size_t i, out, n;
    int rc;

    if (st == NULL || written == NULL || (src_len && src == NULL)) return -1;
    if (st->finished && src_len != 0) return -1;

    out = 0;

    for (i = 0; i < src_len; i++) {
        if (st->pending_len >= 4) return -1;
        st->pending[st->pending_len++] = src[i];

        if (st->pending_len == 4) {
            if (out > dst_cap) return -2;
            rc = grpc_web_b64_decode_quartet(st->pending,
                dst + out, dst_cap - out, &n);
            if (rc != 0) return rc;

            if (st->pending[2] == '=' || st->pending[3] == '=') {
                st->finished = 1;
                if (i + 1 != src_len) return -1;
            }

            out += n;
            st->pending_len = 0;
        }
    }

    if (final) {
        if (st->pending_len != 0) return -1;
        st->finished = 1;
    }

    *written = out;
    return 0;
}

int
grpc_web_b64_encode_update(grpc_web_b64_encoder_t *st,
    const uint8_t *src, size_t src_len, uint8_t *dst, size_t dst_cap,
    size_t *written, int final)
{
    size_t i, out;
    uint8_t b0, b1, b2;

    if (st == NULL || written == NULL || (src_len && src == NULL)) return -1;

    out = 0;
    i = 0;

    while (i < src_len) {
        st->pending[st->pending_len++] = src[i++];

        if (st->pending_len == 3) {
            if (dst_cap - out < 4) return -2;

            b0 = st->pending[0];
            b1 = st->pending[1];
            b2 = st->pending[2];

            dst[out++] = grpc_web_b64_table[b0 >> 2];
            dst[out++] = grpc_web_b64_table[((b0 & 0x03) << 4) | (b1 >> 4)];
            dst[out++] = grpc_web_b64_table[((b1 & 0x0f) << 2) | (b2 >> 6)];
            dst[out++] = grpc_web_b64_table[b2 & 0x3f];

            st->pending_len = 0;
        }
    }

    if (final && st->pending_len != 0) {
        if (dst_cap - out < 4) return -2;

        b0 = st->pending[0];
        b1 = st->pending_len > 1 ? st->pending[1] : 0;

        dst[out++] = grpc_web_b64_table[b0 >> 2];
        dst[out++] = grpc_web_b64_table[((b0 & 0x03) << 4) | (b1 >> 4)];

        if (st->pending_len == 2) {
            dst[out++] = grpc_web_b64_table[(b1 & 0x0f) << 2];
            dst[out++] = '=';
        } else {
            dst[out++] = '=';
            dst[out++] = '=';
        }

        st->pending_len = 0;
    }

    *written = out;
    return 0;
}
