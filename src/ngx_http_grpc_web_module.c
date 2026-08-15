/*
 * ngx_http_grpc_web_module
 *
 * Minimal gRPC-Web protocol adapter layered in front of ngx_http_grpc_module.
 * M2 implements binary unary request/response adaptation.
 * M3 adds incremental grpc-web-text request decoding while response text
 * encoding intentionally remains deferred to M4.
 */

#include <ngx_config.h>
#include <ngx_core.h>
#include <ngx_http.h>

#include "grpc_web_base64.h"
#include "grpc_web_frame.h"

typedef enum {
    NGX_GRPC_WEB_MODE_NONE = 0,
    NGX_GRPC_WEB_MODE_BINARY,
    NGX_GRPC_WEB_MODE_TEXT
} ngx_grpc_web_mode_e;

typedef struct {
    ngx_flag_t enabled;
    size_t max_frame_size;
} ngx_http_grpc_web_loc_conf_t;

typedef struct {
    ngx_grpc_web_mode_e mode;
    ngx_str_t downstream_content_type;
    grpc_web_b64_decoder_t request_decoder;
    grpc_web_b64_encoder_t response_encoder;
    grpc_web_frame_parser_t response_frame;
    size_t decoded_request_size;
    unsigned active:1;
    unsigned request_finished:1;
    unsigned trailers_sent:1;
} ngx_http_grpc_web_ctx_t;

static void *ngx_http_grpc_web_create_loc_conf(ngx_conf_t *cf);
static char *ngx_http_grpc_web_merge_loc_conf(ngx_conf_t *cf,
    void *parent, void *child);
static ngx_int_t ngx_http_grpc_web_init(ngx_conf_t *cf);

static ngx_int_t ngx_http_grpc_web_rewrite_handler(ngx_http_request_t *r);
static ngx_int_t ngx_http_grpc_web_request_body_filter(ngx_http_request_t *r,
    ngx_chain_t *in);
static ngx_int_t ngx_http_grpc_web_header_filter(ngx_http_request_t *r);
static ngx_int_t ngx_http_grpc_web_body_filter(ngx_http_request_t *r,
    ngx_chain_t *in);

static ngx_int_t ngx_http_grpc_web_ensure_te(ngx_http_request_t *r);
static ngx_int_t ngx_http_grpc_web_decode_text_request(
    ngx_http_request_t *r, ngx_http_grpc_web_ctx_t *ctx,
    ngx_chain_t *in, ngx_chain_t **out);
static ngx_chain_t *ngx_http_grpc_web_build_trailer_frame(
    ngx_http_request_t *r);

static ngx_http_request_body_filter_pt ngx_http_grpc_web_next_request_body_filter;
static ngx_http_output_header_filter_pt ngx_http_grpc_web_next_header_filter;
static ngx_http_output_body_filter_pt ngx_http_grpc_web_next_body_filter;

static ngx_command_t ngx_http_grpc_web_commands[] = {
    {
        ngx_string("grpc_web"),
        NGX_HTTP_MAIN_CONF|NGX_HTTP_SRV_CONF|NGX_HTTP_LOC_CONF|NGX_CONF_FLAG,
        ngx_conf_set_flag_slot,
        NGX_HTTP_LOC_CONF_OFFSET,
        offsetof(ngx_http_grpc_web_loc_conf_t, enabled),
        NULL
    },
    {
        ngx_string("grpc_web_max_frame_size"),
        NGX_HTTP_MAIN_CONF|NGX_HTTP_SRV_CONF|NGX_HTTP_LOC_CONF|NGX_CONF_TAKE1,
        ngx_conf_set_size_slot,
        NGX_HTTP_LOC_CONF_OFFSET,
        offsetof(ngx_http_grpc_web_loc_conf_t, max_frame_size),
        NULL
    },
    ngx_null_command
};

static ngx_http_module_t ngx_http_grpc_web_module_ctx = {
    NULL,
    ngx_http_grpc_web_init,
    NULL,
    NULL,
    NULL,
    NULL,
    ngx_http_grpc_web_create_loc_conf,
    ngx_http_grpc_web_merge_loc_conf
};

ngx_module_t ngx_http_grpc_web_module = {
    NGX_MODULE_V1,
    &ngx_http_grpc_web_module_ctx,
    ngx_http_grpc_web_commands,
    NGX_HTTP_MODULE,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NGX_MODULE_V1_PADDING
};

static ngx_int_t
ngx_http_grpc_web_content_type_mode(ngx_http_request_t *r)
{
    ngx_table_elt_t *ct;
    ngx_str_t v;

    ct = r->headers_in.content_type;
    if (ct == NULL) {
        return NGX_GRPC_WEB_MODE_NONE;
    }

    v = ct->value;

    if (v.len >= sizeof("application/grpc-web-text") - 1
        && ngx_strncasecmp(v.data,
                          (u_char *) "application/grpc-web-text",
                          sizeof("application/grpc-web-text") - 1) == 0)
    {
        return NGX_GRPC_WEB_MODE_TEXT;
    }

    if (v.len >= sizeof("application/grpc-web") - 1
        && ngx_strncasecmp(v.data,
                          (u_char *) "application/grpc-web",
                          sizeof("application/grpc-web") - 1) == 0)
    {
        return NGX_GRPC_WEB_MODE_BINARY;
    }

    return NGX_GRPC_WEB_MODE_NONE;
}

static ngx_int_t
ngx_http_grpc_web_ensure_te(ngx_http_request_t *r)
{
    ngx_table_elt_t *te;

    te = r->headers_in.te;

    if (te == NULL) {
        te = ngx_list_push(&r->headers_in.headers);
        if (te == NULL) {
            return NGX_ERROR;
        }

        te->hash = 1;
        ngx_str_set(&te->key, "TE");
        ngx_str_set(&te->value, "trailers");
        te->lowcase_key = (u_char *) "te";
        r->headers_in.te = te;
        return NGX_OK;
    }

    ngx_str_set(&te->value, "trailers");
    return NGX_OK;
}

static ngx_int_t
ngx_http_grpc_web_rewrite_handler(ngx_http_request_t *r)
{
    ngx_http_grpc_web_ctx_t *ctx;
    ngx_http_grpc_web_loc_conf_t *glcf;
    ngx_table_elt_t *ct;
    ngx_int_t mode;

    glcf = ngx_http_get_module_loc_conf(r, ngx_http_grpc_web_module);

    if (!glcf->enabled) {
        return NGX_DECLINED;
    }

    mode = ngx_http_grpc_web_content_type_mode(r);
    if (mode == NGX_GRPC_WEB_MODE_NONE) {
        return NGX_DECLINED;
    }

    ctx = ngx_http_get_module_ctx(r, ngx_http_grpc_web_module);
    if (ctx != NULL) {
        return NGX_DECLINED;
    }

    ctx = ngx_pcalloc(r->pool, sizeof(ngx_http_grpc_web_ctx_t));
    if (ctx == NULL) {
        return NGX_HTTP_INTERNAL_SERVER_ERROR;
    }

    ctx->active = 1;
    ctx->mode = (ngx_grpc_web_mode_e) mode;
    grpc_web_b64_decoder_init(&ctx->request_decoder);
    grpc_web_b64_encoder_init(&ctx->response_encoder);
    grpc_web_frame_parser_init(&ctx->response_frame);

    ct = r->headers_in.content_type;
    ctx->downstream_content_type = ct->value;

    ngx_http_set_ctx(r, ctx, ngx_http_grpc_web_module);

    ngx_str_set(&ct->value, "application/grpc");

    if (ngx_http_grpc_web_ensure_te(r) != NGX_OK) {
        return NGX_HTTP_INTERNAL_SERVER_ERROR;
    }

    if (ctx->mode == NGX_GRPC_WEB_MODE_TEXT) {
        r->headers_in.content_length = NULL;
    }

    return NGX_DECLINED;
}

static ngx_int_t
ngx_http_grpc_web_decode_text_request(ngx_http_request_t *r,
    ngx_http_grpc_web_ctx_t *ctx, ngx_chain_t *in, ngx_chain_t **out)
{
    int rc;
    size_t cap, max_body, src_len, written;
    u_char *src;
    ngx_buf_t *b, *ob;
    ngx_chain_t *cl, *ol, **ll;
    ngx_http_grpc_web_loc_conf_t *glcf;

    *out = NULL;
    ll = out;

    glcf = ngx_http_get_module_loc_conf(r, ngx_http_grpc_web_module);
    if (glcf->max_frame_size > NGX_MAX_SIZE_T_VALUE - GRPC_WEB_FRAME_HEADER_SIZE) {
        max_body = NGX_MAX_SIZE_T_VALUE;
    } else {
        max_body = glcf->max_frame_size + GRPC_WEB_FRAME_HEADER_SIZE;
    }

    for (cl = in; cl != NULL; cl = cl->next) {
        b = cl->buf;

        if (ctx->request_finished) {
            ngx_log_error(NGX_LOG_ERR, r->connection->log, 0,
                          "grpc-web duplicate request data after final buffer");
            return NGX_HTTP_BAD_REQUEST;
        }

        if (ngx_buf_in_memory(b)) {
            src = b->pos;
            src_len = (size_t) (b->last - b->pos);
        } else {
            if (ngx_buf_size(b) != 0) {
                ngx_log_error(NGX_LOG_ERR, r->connection->log, 0,
                              "grpc-web text request data is not in memory");
                return NGX_HTTP_INTERNAL_SERVER_ERROR;
            }

            src = NULL;
            src_len = 0;
        }

        if (src_len > NGX_MAX_SIZE_T_VALUE - 2) {
            return NGX_HTTP_REQUEST_ENTITY_TOO_LARGE;
        }

        cap = src_len + 2;
        if (cap == 0) {
            cap = 1;
        }

        ob = ngx_create_temp_buf(r->pool, cap);
        if (ob == NULL) {
            return NGX_HTTP_INTERNAL_SERVER_ERROR;
        }

        written = 0;
        rc = grpc_web_b64_decode_update(&ctx->request_decoder,
            src, src_len, ob->last, cap, &written, b->last_buf);

        if (rc == -1) {
            ngx_log_error(NGX_LOG_INFO, r->connection->log, 0,
                          "grpc-web malformed base64 request body");
            return NGX_HTTP_BAD_REQUEST;
        }

        if (rc != 0) {
            ngx_log_error(NGX_LOG_ERR, r->connection->log, 0,
                          "grpc-web base64 decoder output sizing failure");
            return NGX_HTTP_INTERNAL_SERVER_ERROR;
        }

        if (ctx->decoded_request_size > max_body
            || written > max_body - ctx->decoded_request_size)
        {
            ngx_log_error(NGX_LOG_INFO, r->connection->log, 0,
                          "grpc-web decoded request body too large");
            return NGX_HTTP_REQUEST_ENTITY_TOO_LARGE;
        }

        ctx->decoded_request_size += written;
        ob->last += written;
        ob->flush = b->flush;
        ob->sync = b->sync;
        ob->last_buf = b->last_buf;
        ob->last_in_chain = b->last_in_chain;

        if (ngx_buf_in_memory(b)) {
            b->pos = b->last;
        }

        if (written != 0 || ob->last_buf || ob->flush || ob->sync) {
            ol = ngx_alloc_chain_link(r->pool);
            if (ol == NULL) {
                return NGX_HTTP_INTERNAL_SERVER_ERROR;
            }

            ol->buf = ob;
            ol->next = NULL;
            *ll = ol;
            ll = &ol->next;
        }

        if (b->last_buf) {
            if (ctx->decoded_request_size > (size_t) NGX_MAX_OFF_T_VALUE) {
                return NGX_HTTP_REQUEST_ENTITY_TOO_LARGE;
            }

            ctx->request_finished = 1;
            r->headers_in.content_length_n = (off_t) ctx->decoded_request_size;
        }
    }

    return NGX_OK;
}

static ngx_int_t
ngx_http_grpc_web_request_body_filter(ngx_http_request_t *r, ngx_chain_t *in)
{
    ngx_int_t rc;
    ngx_chain_t *out;
    ngx_http_grpc_web_ctx_t *ctx;

    ctx = ngx_http_get_module_ctx(r, ngx_http_grpc_web_module);
    if (ctx == NULL || !ctx->active || ctx->mode != NGX_GRPC_WEB_MODE_TEXT) {
        return ngx_http_grpc_web_next_request_body_filter(r, in);
    }

    if (in == NULL) {
        return ngx_http_grpc_web_next_request_body_filter(r, NULL);
    }

    rc = ngx_http_grpc_web_decode_text_request(r, ctx, in, &out);
    if (rc != NGX_OK) {
        return rc;
    }

    return ngx_http_grpc_web_next_request_body_filter(r, out);
}

static ngx_int_t
ngx_http_grpc_web_header_filter(ngx_http_request_t *r)
{
    ngx_http_grpc_web_ctx_t *ctx;

    ctx = ngx_http_get_module_ctx(r, ngx_http_grpc_web_module);
    if (ctx == NULL || !ctx->active
        || ctx->mode != NGX_GRPC_WEB_MODE_BINARY)
    {
        return ngx_http_grpc_web_next_header_filter(r);
    }

    r->headers_out.content_type = ctx->downstream_content_type;
    r->headers_out.content_type_len = ctx->downstream_content_type.len;
    r->headers_out.content_type_lowcase = NULL;
    r->headers_out.content_type_hash = 0;

    if (r->headers_out.content_length != NULL) {
        r->headers_out.content_length->hash = 0;
        r->headers_out.content_length = NULL;
    }
    r->headers_out.content_length_n = -1;
    r->expect_trailers = 1;

    return ngx_http_grpc_web_next_header_filter(r);
}

static ngx_chain_t *
ngx_http_grpc_web_build_trailer_frame(ngx_http_request_t *r)
{
    size_t payload_len, line_len;
    uint8_t header[GRPC_WEB_FRAME_HEADER_SIZE];
    ngx_buf_t *b;
    ngx_uint_t i;
    ngx_chain_t *cl;
    ngx_list_part_t *part;
    ngx_table_elt_t *h;
    ngx_http_grpc_web_loc_conf_t *glcf;

    payload_len = 0;
    part = &r->headers_out.trailers.part;
    h = part->elts;

    for (i = 0; /* void */; i++) {
        if (i >= part->nelts) {
            if (part->next == NULL) {
                break;
            }
            part = part->next;
            h = part->elts;
            i = 0;
        }

        if (h[i].hash == 0) {
            continue;
        }

        if (h[i].key.len > NGX_MAX_SIZE_T_VALUE - h[i].value.len - 3) {
            return NGX_CHAIN_ERROR;
        }

        line_len = h[i].key.len + 1 + h[i].value.len + 2;
        if (payload_len > NGX_MAX_SIZE_T_VALUE - line_len) {
            return NGX_CHAIN_ERROR;
        }
        payload_len += line_len;
    }

    glcf = ngx_http_get_module_loc_conf(r, ngx_http_grpc_web_module);

    if (payload_len == 0 || payload_len > 0xffffffffu
        || payload_len > glcf->max_frame_size)
    {
        ngx_log_error(NGX_LOG_ERR, r->connection->log, 0,
                      "grpc-web invalid trailer block size: %uz", payload_len);
        return NGX_CHAIN_ERROR;
    }

    if (payload_len > NGX_MAX_SIZE_T_VALUE - GRPC_WEB_FRAME_HEADER_SIZE) {
        return NGX_CHAIN_ERROR;
    }

    b = ngx_create_temp_buf(r->pool,
                            GRPC_WEB_FRAME_HEADER_SIZE + payload_len);
    if (b == NULL) {
        return NGX_CHAIN_ERROR;
    }

    grpc_web_frame_write_header(header, GRPC_WEB_TRAILER_FLAG,
                                (uint32_t) payload_len);
    b->last = ngx_cpymem(b->last, header, GRPC_WEB_FRAME_HEADER_SIZE);

    part = &r->headers_out.trailers.part;
    h = part->elts;

    for (i = 0; /* void */; i++) {
        if (i >= part->nelts) {
            if (part->next == NULL) {
                break;
            }
            part = part->next;
            h = part->elts;
            i = 0;
        }

        if (h[i].hash == 0) {
            continue;
        }

        b->last = ngx_cpymem(b->last, h[i].key.data, h[i].key.len);
        *b->last++ = ':';
        b->last = ngx_cpymem(b->last, h[i].value.data, h[i].value.len);
        *b->last++ = CR;
        *b->last++ = LF;
        h[i].hash = 0;
    }

    b->last_buf = 1;
    b->last_in_chain = 1;

    cl = ngx_alloc_chain_link(r->pool);
    if (cl == NULL) {
        return NGX_CHAIN_ERROR;
    }

    cl->buf = b;
    cl->next = NULL;

    r->expect_trailers = 0;
    return cl;
}

static ngx_int_t
ngx_http_grpc_web_body_filter(ngx_http_request_t *r, ngx_chain_t *in)
{
    ngx_http_grpc_web_ctx_t *ctx;
    ngx_chain_t *cl, *last, *trailers;

    ctx = ngx_http_get_module_ctx(r, ngx_http_grpc_web_module);
    if (ctx == NULL || !ctx->active
        || ctx->mode != NGX_GRPC_WEB_MODE_BINARY
        || ctx->trailers_sent)
    {
        return ngx_http_grpc_web_next_body_filter(r, in);
    }

    last = NULL;
    for (cl = in; cl != NULL; cl = cl->next) {
        last = cl;
        if (cl->buf->last_buf) {
            break;
        }
    }

    if (cl == NULL) {
        return ngx_http_grpc_web_next_body_filter(r, in);
    }

    trailers = ngx_http_grpc_web_build_trailer_frame(r);
    if (trailers == NGX_CHAIN_ERROR) {
        return NGX_ERROR;
    }

    cl->buf->last_buf = 0;
    cl->buf->last_in_chain = 0;

    while (last->next != NULL) {
        last = last->next;
    }
    last->next = trailers;

    ctx->trailers_sent = 1;

    return ngx_http_grpc_web_next_body_filter(r, in);
}

static void *
ngx_http_grpc_web_create_loc_conf(ngx_conf_t *cf)
{
    ngx_http_grpc_web_loc_conf_t *conf;

    conf = ngx_pcalloc(cf->pool, sizeof(ngx_http_grpc_web_loc_conf_t));
    if (conf == NULL) {
        return NULL;
    }

    conf->enabled = NGX_CONF_UNSET;
    conf->max_frame_size = NGX_CONF_UNSET_SIZE;

    return conf;
}

static char *
ngx_http_grpc_web_merge_loc_conf(ngx_conf_t *cf, void *parent, void *child)
{
    ngx_http_grpc_web_loc_conf_t *prev = parent;
    ngx_http_grpc_web_loc_conf_t *conf = child;

    ngx_conf_merge_value(conf->enabled, prev->enabled, 0);
    ngx_conf_merge_size_value(conf->max_frame_size, prev->max_frame_size,
                              64 * 1024 * 1024);

    return NGX_CONF_OK;
}

static ngx_int_t
ngx_http_grpc_web_init(ngx_conf_t *cf)
{
    ngx_http_core_main_conf_t *cmcf;
    ngx_http_handler_pt *h;

    cmcf = ngx_http_conf_get_module_main_conf(cf, ngx_http_core_module);

    h = ngx_array_push(&cmcf->phases[NGX_HTTP_REWRITE_PHASE].handlers);
    if (h == NULL) {
        return NGX_ERROR;
    }
    *h = ngx_http_grpc_web_rewrite_handler;

    ngx_http_grpc_web_next_request_body_filter = ngx_http_top_request_body_filter;
    ngx_http_top_request_body_filter = ngx_http_grpc_web_request_body_filter;

    ngx_http_grpc_web_next_header_filter = ngx_http_top_header_filter;
    ngx_http_top_header_filter = ngx_http_grpc_web_header_filter;

    ngx_http_grpc_web_next_body_filter = ngx_http_top_body_filter;
    ngx_http_top_body_filter = ngx_http_grpc_web_body_filter;

    return NGX_OK;
}
