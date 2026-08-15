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
test_decode_all_two_way_splits(void)
{
    static const uint8_t encoded[] = "AAAAAAVoZWxsbw==";
    static const uint8_t expected[] = {
        0x00, 0x00, 0x00, 0x00, 0x05, 'h', 'e', 'l', 'l', 'o'
    };
    grpc_web_b64_decoder_t st;
    uint8_t out[64];
    size_t split, n, total;

    for (split = 0; split <= sizeof(encoded) - 1; split++) {
        grpc_web_b64_decoder_init(&st);
        total = 0;

        assert(grpc_web_b64_decode_update(&st,
            encoded, split, out + total, sizeof(out) - total, &n, 0) == 0);
        total += n;

        assert(grpc_web_b64_decode_update(&st,
            encoded + split, (sizeof(encoded) - 1) - split,
            out + total, sizeof(out) - total, &n, 1) == 0);
        total += n;

        assert(total == sizeof(expected));
        assert(memcmp(out, expected, sizeof(expected)) == 0);
    }
}

static void
test_decode_all_three_way_splits(void)
{
    static const uint8_t encoded[] = "AAAAAAVoZWxsbw==";
    static const uint8_t expected[] = {
        0x00, 0x00, 0x00, 0x00, 0x05, 'h', 'e', 'l', 'l', 'o'
    };
    grpc_web_b64_decoder_t st;
    uint8_t out[64];
    size_t a, b, n, total, len;

    len = sizeof(encoded) - 1;

    for (a = 0; a <= len; a++) {
        for (b = a; b <= len; b++) {
            grpc_web_b64_decoder_init(&st);
            total = 0;

            assert(grpc_web_b64_decode_update(&st,
                encoded, a, out + total, sizeof(out) - total, &n, 0) == 0);
            total += n;

            assert(grpc_web_b64_decode_update(&st,
                encoded + a, b - a, out + total, sizeof(out) - total,
                &n, 0) == 0);
            total += n;

            assert(grpc_web_b64_decode_update(&st,
                encoded + b, len - b, out + total, sizeof(out) - total,
                &n, 1) == 0);
            total += n;

            assert(total == sizeof(expected));
            assert(memcmp(out, expected, sizeof(expected)) == 0);
        }
    }
}

static void
test_decode_padding(void)
{
    grpc_web_b64_decoder_t st;
    uint8_t out[8];
    size_t n;

    grpc_web_b64_decoder_init(&st);
    assert(grpc_web_b64_decode_update(&st,
        (const uint8_t *) "Zg==", 4, out, sizeof(out), &n, 1) == 0);
    assert(n == 1 && out[0] == 'f');

    grpc_web_b64_decoder_init(&st);
    assert(grpc_web_b64_decode_update(&st,
        (const uint8_t *) "Zm8=", 4, out, sizeof(out), &n, 1) == 0);
    assert(n == 2 && memcmp(out, "fo", 2) == 0);
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

static void
test_reject_invalid_alphabet_and_padding(void)
{
    static const char *bad[] = {
        "!!!!",
        "=m9v",
        "Zm=v",
        "Z===",
        "Zg==AAAA",
        "Zm9v="
    };
    grpc_web_b64_decoder_t st;
    uint8_t out[64];
    size_t i, n;

    for (i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        grpc_web_b64_decoder_init(&st);
        assert(grpc_web_b64_decode_update(&st,
            (const uint8_t *) bad[i], strlen(bad[i]),
            out, sizeof(out), &n, 1) == -1);
    }
}

int
main(void)
{
    test_encode_fragmented();
    test_decode_fragmented();
    test_decode_all_two_way_splits();
    test_decode_all_three_way_splits();
    test_decode_padding();
    test_reject_incomplete();
    test_reject_invalid_alphabet_and_padding();
    puts("base64 tests: ok");
    return 0;
}
