#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "../../src/grpc_web_base64.h"

static void
test_encode_fragmented(void)
{
    grpc_web_b64_encoder_t st;
    uint8_t out[64];
    size_t n1, n2, n3, total;

    grpc_web_b64_encoder_init(&st);

    assert(grpc_web_b64_encode_update(&st,
        (const uint8_t *) "f", 1, out, sizeof(out), &n1, 0) == 0);
    assert(n1 == 0);

    assert(grpc_web_b64_encode_update(&st,
        (const uint8_t *) "o", 1, out, sizeof(out), &n2, 0) == 0);
    assert(n2 == 0);

    assert(grpc_web_b64_encode_update(&st,
        (const uint8_t *) "o", 1, out, sizeof(out), &n3, 1) == 0);
    total = n1 + n2 + n3;

    assert(total == 4);
    assert(memcmp(out, "Zm9v", 4) == 0);
}

static void
test_decode_fragmented(void)
{
    grpc_web_b64_decoder_t st;
    uint8_t out[64];
    size_t n, total;

    grpc_web_b64_decoder_init(&st);
    total = 0;

    assert(grpc_web_b64_decode_update(&st,
        (const uint8_t *) "Z", 1, out + total, sizeof(out) - total, &n, 0) == 0);
    total += n;
    assert(grpc_web_b64_decode_update(&st,
        (const uint8_t *) "m9", 2, out + total, sizeof(out) - total, &n, 0) == 0);
    total += n;
    assert(grpc_web_b64_decode_update(&st,
        (const uint8_t *) "v", 1, out + total, sizeof(out) - total, &n, 1) == 0);
    total += n;

    assert(total == 3);
    assert(memcmp(out, "foo", 3) == 0);
}

static void
test_reject_incomplete(void)
{
    grpc_web_b64_decoder_t st;
    uint8_t out[64];
    size_t n;

    grpc_web_b64_decoder_init(&st);
    assert(grpc_web_b64_decode_update(&st,
        (const uint8_t *) "Zm9", 3, out, sizeof(out), &n, 1) == -1);
}

int
main(void)
{
    test_encode_fragmented();
    test_decode_fragmented();
    test_reject_incomplete();
    puts("base64 tests: ok");
    return 0;
}
