#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "cJSON.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "report.h"
#include "uplink.h"
#include "webui.h"

static const char *TAG = "webui";

/* The page itself, linked in from web/index.html by the component's
 * EMBED_TXTFILES. Kept as one file so there is exactly one request to serve and
 * nothing to go missing. */
extern const char index_html_start[] asm("_binary_index_html_start");
extern const char index_html_end[]   asm("_binary_index_html_end");

static nodecfg_t          *s_cfg;
static webui_hooks_t       s_hooks;
static httpd_handle_t      s_server;

/* Bodies are small (the settings form is the largest at a few hundred bytes)
 * and anything larger is not something this UI sends. */
#define BODY_MAX 1024

static esp_err_t send_json(httpd_req_t *req, cJSON *root)
{
    char *text = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!text) return httpd_resp_send_500(req);

    httpd_resp_set_type(req, "application/json");
    /* The page polls this every two seconds; caching it would show a field
     * that stopped reporting as one that is fine. */
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    esp_err_t err = httpd_resp_sendstr(req, text);
    free(text);
    return err;
}

/* ------------------------------------------------------------------ routes */

static esp_err_t get_index(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, index_html_start,
                           (ssize_t)(index_html_end - index_html_start - 1));
}

static esp_err_t get_status(httpd_req_t *req)
{
    return send_json(req, report_status());
}

static esp_err_t get_nodes(httpd_req_t *req)
{
    return send_json(req, report_nodes());
}

/*
 * Networks in range, so the site's WiFi can be picked from a list rather than
 * typed from memory while standing next to the gateway. The scan takes a couple
 * of seconds and briefly costs the station link, so it happens only when
 * somebody presses the button.
 */
static esp_err_t get_wifi_scan(httpd_req_t *req)
{
    uplink_ap_t found[20];
    int n = uplink_scan(found, (int)(sizeof(found) / sizeof(found[0])));

    cJSON *root = cJSON_CreateObject();
    cJSON *arr = cJSON_AddArrayToObject(root, "networks");
    for (int i = 0; i < n; i++) {
        cJSON *o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "ssid", found[i].ssid);
        cJSON_AddNumberToObject(o, "rssi", found[i].rssi);
        cJSON_AddBoolToObject(o, "secured", found[i].secured);
        cJSON_AddItemToArray(arr, o);
    }
    return send_json(req, root);
}

static char *read_body(httpd_req_t *req)
{
    if (req->content_len <= 0 || req->content_len >= BODY_MAX) return NULL;
    char *buf = malloc((size_t)req->content_len + 1);
    if (!buf) return NULL;

    int got = 0;
    while (got < req->content_len) {
        int n = httpd_req_recv(req, buf + got, (size_t)(req->content_len - got));
        if (n <= 0) { free(buf); return NULL; }
        got += n;
    }
    buf[got] = '\0';
    return buf;
}

/* Only the fields the form actually sends, and only when they are present:
 * a partial save must not blank the settings it did not mention. */
static void apply_string(const cJSON *root, const char *key, char *dst, size_t cap)
{
    const cJSON *j = cJSON_GetObjectItem(root, key);
    if (!cJSON_IsString(j)) return;
    strncpy(dst, j->valuestring, cap - 1);
    dst[cap - 1] = '\0';
}

static esp_err_t post_settings(httpd_req_t *req)
{
    char *body = read_body(req);
    if (!body) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "body");
        return ESP_FAIL;
    }
    cJSON *root = cJSON_Parse(body);
    free(body);
    if (!root) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "json");
        return ESP_FAIL;
    }

    apply_string(root, "wifi_ssid", s_cfg->wifi_ssid, sizeof(s_cfg->wifi_ssid));
    apply_string(root, "wifi_pass", s_cfg->wifi_pass, sizeof(s_cfg->wifi_pass));
    apply_string(root, "api_url",   s_cfg->api_url,   sizeof(s_cfg->api_url));
    apply_string(root, "mqtt_host", s_cfg->mqtt_host, sizeof(s_cfg->mqtt_host));
    apply_string(root, "site",      s_cfg->site_slug, sizeof(s_cfg->site_slug));
    apply_string(root, "gateway_id",s_cfg->gateway_id,sizeof(s_cfg->gateway_id));
    apply_string(root, "sms",       s_cfg->sms_recipients, sizeof(s_cfg->sms_recipients));
    apply_string(root, "push_url",  s_cfg->push_url,  sizeof(s_cfg->push_url));

    const cJSON *ap = cJSON_GetObjectItem(root, "ap_pass");
    if (cJSON_IsString(ap) && strlen(ap->valuestring) >= 8)
        apply_string(root, "ap_pass", s_cfg->ap_pass, sizeof(s_cfg->ap_pass));

    bool wifi_changed = cJSON_HasObjectItem(root, "wifi_ssid") ||
                        cJSON_HasObjectItem(root, "wifi_pass");
    cJSON_Delete(root);

    bool ok = nodecfg_save(s_cfg);
    ESP_LOGW(TAG, "settings written from the web UI: %s", ok ? "saved" : "NVS FAILED");

    char note[128];
    if (!ok) {
        snprintf(note, sizeof(note), "NVS write failed -- nothing was saved");
    } else if (wifi_changed) {
        /* Join now rather than at the next boot. Making somebody power-cycle a
         * gateway on a pole to find out whether they typed the password
         * correctly is not a design. */
        uplink_wifi_apply();
        snprintf(note, sizeof(note),
                 "saved -- joining \"%s\" now; the network card shows the result",
                 s_cfg->wifi_ssid);
    } else {
        snprintf(note, sizeof(note), "saved");
    }

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddBoolToObject(resp, "saved", ok);
    cJSON_AddStringToObject(resp, "note", note);
    return send_json(req, resp);
}

static esp_err_t post_sms_test(httpd_req_t *req)
{
    int sent = 0;
    if (s_hooks.test_sms)
        sent = s_hooks.test_sms("MINEGUARD test message from the gateway. "
                                "If you are reading this, the offline alerting "
                                "path works.");

    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "recipients", sent);
    cJSON_AddBoolToObject(root, "ok", sent > 0);
    return send_json(req, root);
}

static esp_err_t post_reboot(httpd_req_t *req)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddBoolToObject(root, "rebooting", true);
    esp_err_t err = send_json(req, root);

    /* Answer first, restart second: a reboot that races the response leaves the
     * person holding the phone unsure whether anything happened. */
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
    return err;
}

/* ------------------------------------------------------------------- start */

esp_err_t webui_start(nodecfg_t *cfg, const webui_hooks_t *hooks)
{
    s_cfg = cfg;
    if (hooks) s_hooks = *hooks;

    httpd_config_t hc = HTTPD_DEFAULT_CONFIG();
    hc.server_port = 80;
    hc.max_uri_handlers = 8;
    hc.lru_purge_enable = true;
    /* Below the radio and uplink tasks. A phone refreshing a page must never
     * delay a frame off the air or a batch going out. */
    hc.task_priority = 2;
    hc.stack_size = 8192;

    esp_err_t err = httpd_start(&s_server, &hc);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "web UI did not start: %s", esp_err_to_name(err));
        return err;
    }

    static const httpd_uri_t routes[] = {
        { .uri = "/",             .method = HTTP_GET,  .handler = get_index },
        { .uri = "/api/status",   .method = HTTP_GET,  .handler = get_status },
        { .uri = "/api/nodes",    .method = HTTP_GET,  .handler = get_nodes },
        { .uri = "/api/wifi/scan",.method = HTTP_GET,  .handler = get_wifi_scan },
        { .uri = "/api/settings", .method = HTTP_POST, .handler = post_settings },
        { .uri = "/api/sms-test", .method = HTTP_POST, .handler = post_sms_test },
        { .uri = "/api/reboot",   .method = HTTP_POST, .handler = post_reboot },
    };
    for (size_t i = 0; i < sizeof(routes) / sizeof(routes[0]); i++)
        httpd_register_uri_handler(s_server, &routes[i]);

    ESP_LOGI(TAG, "web UI up on port 80");
    return ESP_OK;
}
