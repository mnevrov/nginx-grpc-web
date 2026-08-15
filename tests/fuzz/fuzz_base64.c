#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "../../src/grpc_web_base64.h"

static size_t
encoded_capacity(size_t len)
{
    if (len > (SIZE_MAX - 2) / 4 * 3) {
        return 0;
    }

    return ((len + 2) / 3) * 4;
}

int
LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    int rc;
    size_t cap, decoded_cap, encoded_len, decoded_len, n, off, chunk;
    uint8_t *encoded, *decoded;
    grpc_web_b64_decoder_t decoder;
    grpc_web_b64_encoder_t encoder;

    cap = encoded_capacity(size);
    if (cap == 0) {
        return 0;
    }

    encoded = malloc(cap == 0 ? 1 : cap);
    decoded_cap = size + 3;
    decoded = malloc(decoded_cap == 0 ? 1 : decoded_cap);
    if (encoded == NULL || decoded == NULL) {
        free(encoded);
        free(decoded);
        return 0;
    }

    /* Property 1: arbitrary bytes round-trip through our encoder/decoder. */
    grpc_web_b64_encoder_init(&encoder);
    encoded_len = 0;
    off = 0;

    while (off < size) {
        chunk = 1 + ((data[off] + off) % 17);
        if (chunk > size - off) {
            chunk = size - off;
        }

        n = 0;
        rc = grpc_web_b64_encode_update(&encoder,
            data + off, chunk, encoded + encoded_len, cap - encoded_len,
            &n, off + chunk == size);
        assert(rc == 0);
        encoded_len += n;
        off += chunk;
    }

    if (size == 0) {
        n = 0;
        rc = grpc_web_b64_encode_update(&encoder,
            NULL, 0, encoded, cap == 0 ? 1 : cap, &n, 1);
        assert(rc == 0);
        encoded_len = n;
    }

    grpc_web_b64_decoder_init(&decoder);
    decoded_len = 0;
    off = 0;

    while (off < encoded_len) {
        chunk = 1 + ((encoded[off] + off) % 13);
        if (chunk > encoded_len - off) {
            chunk = encoded_len - off;
        }

        n = 0;
        rc = grpc_web_b64_decode_update(&decoder,
            encoded + off, chunk, decoded + decoded_len,
            decoded_cap - decoded_len, &n, off + chunk == encoded_len);
        assert(rc == 0);
        decoded_len += n;
        off += chunk;
    }

    if (encoded_len == 0) {
        n = 0;
        rc = grpc_web_b64_decode_update(&decoder,
            NULL, 0, decoded, decoded_cap, &n, 1);
        assert(rc == 0);
        decoded_len = n;
    }

    assert(decoded_len == size);
    assert(size == 0 || memcmp(decoded, data, size) == 0);

    /* Property 2: arbitrary attacker-controlled bytes never escape state. */
    grpc_web_b64_decoder_init(&decoder);
    off = 0;
    decoded_len = 0;

    while (off < size) {
        chunk = 1 + ((data[off] ^ (uint8_t) off) % 11);
        if (chunk > size - off) {
            chunk = size - off;
        }

        n = 0;
        rc = grpc_web_b64_decode_update(&decoder,
            data + off, chunk, decoded + decoded_len,
            decoded_cap - decoded_len, &n, off + chunk == size);

        assert(decoder.pending_len <= 4);
        if (rc != 0) {
            break;
        }

        assert(n <= decoded_cap - decoded_len);
        decoded_len += n;
        off += chunk;
    }

    free(encoded);
    free(decoded);
    return 0;
}
