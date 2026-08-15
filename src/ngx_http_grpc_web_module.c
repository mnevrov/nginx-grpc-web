/*
 * ngx_http_grpc_web_module
 *
 * Bootstrap skeleton.
 *
 * The module is deliberately a no-op protocol adapter at M1: it registers the
 * directive and filter hooks but does not yet rewrite traffic. Each protocol
 * path is enabled only together with its differential/browser tests.
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
    grpc_web_b64_decoder_t request_decoder;
    grpc_web_b64_encoder_t response_encoder;
    grpc_web_frame_parser_t response_frame;
    unsigned active:1;
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
    NULL,                         /* preconfiguration */
    ngx_http_grpc_web_init,       /* postconfiguration */
    NULL,                         /* create main configuration */
    NULL,                         /* init main configuration */
    NULL,                         /* create server configuration */
    NULL,                         /* merge server configuration */
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
ngx_http_grpc_web_rewrite_handler(ngx_http_request_t *r)
{
    ngx_http_grpc_web_ctx_t *ctx;
    ngx_http_grpc_web_loc_conf_t *glcf;
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

    ngx_http_set_ctx(r, ctx, ngx_http_grpc_web_module);

    /*
     * M1 intentionally does not mutate request headers/body.
     * Protocol rewrites land milestone-by-milestone with tests.
     */

    return NGX_DECLINED;
}

static ngx_int_t
ngx_http_grpc_web_request_body_filter(ngx_http_request_t *r, ngx_chain_t *in)
{
    ngx_http_grpc_web_ctx_t *ctx;

    ctx = ngx_http_get_module_ctx(r, ngx_http_grpc_web_module);
    if (ctx == NULL || !ctx->active) {
        return ngx_http_grpc_web_next_request_body_filter(r, in);
    }

    /* M2/M3: transform request path here. */
    return ngx_http_grpc_web_next_request_body_filter(r, in);
}

static ngx_int_t
ngx_http_grpc_web_header_filter(ngx_http_request_t *r)
{
    ngx_http_grpc_web_ctx_t *ctx;

    ctx = ngx_http_get_module_ctx(r, ngx_http_grpc_web_module);
    if (ctx == NULL || !ctx->active) {
        return ngx_http_grpc_web_next_header_filter(r);
    }

    /* M2/M4: rewrite downstream response headers here. */
    return ngx_http_grpc_web_next_header_filter(r);
}

static ngx_int_t
ngx_http_grpc_web_body_filter(ngx_http_request_t *r, ngx_chain_t *in)
{
    ngx_http_grpc_web_ctx_t *ctx;

    ctx = ngx_http_get_module_ctx(r, ngx_http_grpc_web_module);
    if (ctx == NULL || !ctx->active) {
        return ngx_http_grpc_web_next_body_filter(r, in);
    }

    /* M2/M4/M5: encode data + terminal trailer frame here. */
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
