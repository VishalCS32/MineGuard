#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>

#include "cJSON.h"
#include "esp_event.h"
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_sntp.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "mbedtls/base64.h"
#include "mqtt_client.h"
#include "nvs_flash.h"

#include "subnet_proto.h"
#include "uplink.h"

static const char *TAG = "uplink";

#define WIFI_CONNECTED_BIT BIT0
#define HTTP_TIMEOUT_MS    15000
/* 64 frames of 64 bytes encode to ~5.5 kB of base64; the rest is JSON scaffolding. */
#define BODY_CAP           8192
#define RESP_CAP           4096

static const nodecfg_t     *s_cfg;
static uplink_downlink_fn   s_on_downlink;
static EventGroupHandle_t   s_events;
static esp_mqtt_client_handle_t s_mqtt;
static bool                 s_mqtt_up, s_time_valid;
static uint32_t             s_posted, s_failures, s_downlinks;
static uint32_t             s_push_ok, s_push_fail, s_push_last_ms;
static int                  s_wifi_retries;
static esp_timer_handle_t   s_reconnect_timer;
static esp_netif_t         *s_sta_netif;
static char                 s_ap_ssid[33];

static void sntp_start(void);
static void mqtt_start(void);

/* ------------------------------------------------------------------- WiFi */

static void reconnect_cb(void *arg)
{
    (void)arg;
    esp_wifi_connect();
}

static void on_wifi(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg; (void)data;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_events, WIFI_CONNECTED_BIT);
        /* Retry for ever, with a backoff that tops out at half a minute. A
         * gateway whose router is rebooting must reconnect on its own at 4 a.m.
         * with nobody on site; giving up after N attempts is how a site loses a
         * night of telemetry.
         *
         * The wait is a one-shot timer rather than a delay here: this runs on
         * the system event task, and sleeping on it would stall every other
         * event -- including the IP that arrives when the join succeeds. */
        int delay_ms = 1000 * (s_wifi_retries < 30 ? (s_wifi_retries + 1) : 30);
        s_wifi_retries++;
        ESP_LOGW(TAG, "WiFi disconnected; retrying in %d ms", delay_ms);
        esp_timer_start_once(s_reconnect_timer, (uint64_t)delay_ms * 1000);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
        s_wifi_retries = 0;
        ESP_LOGI(TAG, "WiFi up: " IPSTR, IP2STR(&ev->ip_info.ip));
        xEventGroupSetBits(s_events, WIFI_CONNECTED_BIT);
    }
}

/*
 * Station AND access point, always both.
 *
 * The station half is the uplink. The access point half exists so that a person
 * standing next to the gateway with a phone can always reach it -- to read what
 * the field is doing, or to configure a gateway that has never had a network to
 * join. On a mine site the WiFi it is supposed to use is frequently the thing
 * that is broken, and a diagnostic interface that requires the broken component
 * is not a diagnostic interface.
 *
 * It costs nothing that matters: the radio is already powered, the gateway has
 * a battery the size of a brick, and APSTA on the same channel adds no
 * measurable current to a device drawing 150 mA.
 */
static void softap_start(void)
{
    esp_netif_create_default_wifi_ap();

    wifi_config_t ap = {0};
    snprintf(s_ap_ssid, sizeof(s_ap_ssid), "mineguard-%s",
             s_cfg->gateway_id[0] ? s_cfg->gateway_id : "gw");
    strncpy((char *)ap.ap.ssid, s_ap_ssid, sizeof(ap.ap.ssid) - 1);
    ap.ap.ssid_len = (uint8_t)strlen(s_ap_ssid);
    ap.ap.max_connection = 4;
    ap.ap.channel = 6;

    const char *pass = s_cfg->ap_pass[0] ? s_cfg->ap_pass : "mineguard";
    if (strlen(pass) >= 8) {
        strncpy((char *)ap.ap.password, pass, sizeof(ap.ap.password) - 1);
        ap.ap.authmode = WIFI_AUTH_WPA2_PSK;
    } else {
        /* Refuse to fall back to an open network. Anyone who can reach the UI
         * can reconfigure the field and send SMS from the gateway's SIM. */
        ESP_LOGE(TAG, "AP password too short; access point not started");
        return;
    }
    if (!strcmp(pass, "mineguard"))
        ESP_LOGW(TAG, "the access point is still on its default password. "
                      "Anyone in range can reconfigure this gateway: `set ap-pass "
                      "<something>` then `save`");

    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap));
    ESP_LOGI(TAG, "on-site network \"%s\" -- the web UI is at http://192.168.4.1",
             s_ap_ssid);
}

static void wifi_start(void)
{
    const esp_timer_create_args_t timer = { .callback = reconnect_cb,
                                            .name = "wifi-retry" };
    ESP_ERROR_CHECK(esp_timer_create(&timer, &s_reconnect_timer));

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    s_sta_netif = esp_netif_create_default_wifi_sta();

    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                        on_wifi, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                        on_wifi, NULL, NULL));

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    softap_start();

    if (s_cfg->wifi_ssid[0]) {
        wifi_config_t wc = {0};
        strncpy((char *)wc.sta.ssid, s_cfg->wifi_ssid, sizeof(wc.sta.ssid) - 1);
        strncpy((char *)wc.sta.password, s_cfg->wifi_pass, sizeof(wc.sta.password) - 1);
        wc.sta.threshold.authmode = WIFI_AUTH_OPEN;  /* accept whatever the site runs */
        ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    } else {
        ESP_LOGW(TAG, "no uplink WiFi configured -- the mesh, the spool and local "
                      "SMS all still work, and the on-site UI is up on the AP. "
                      "Configure it there, or with `set wifi <ssid> <pass>`");
    }

    /* No power save. The saving is milliamps on a gateway that has a panel and a
     * battery the size of a brick, and the cost is latency on the downlink path
     * that carries configuration to sleeping nodes. */
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_start());
}

void uplink_netinfo(uplink_net_t *out)
{
    memset(out, 0, sizeof(*out));
    out->sta_up = uplink_wifi_up();
    strncpy(out->ap_ssid, s_ap_ssid, sizeof(out->ap_ssid) - 1);
    snprintf(out->ap_ip, sizeof(out->ap_ip), "192.168.4.1");
    out->rssi = 0;

    wifi_sta_list_t clients;
    if (esp_wifi_ap_get_sta_list(&clients) == ESP_OK) out->ap_clients = clients.num;

    if (s_cfg) strncpy(out->sta_ssid, s_cfg->wifi_ssid, sizeof(out->sta_ssid) - 1);

    if (out->sta_up && s_sta_netif) {
        esp_netif_ip_info_t ip;
        if (esp_netif_get_ip_info(s_sta_netif, &ip) == ESP_OK)
            snprintf(out->sta_ip, sizeof(out->sta_ip), IPSTR, IP2STR(&ip.ip));
        wifi_ap_record_t ap;
        if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) out->rssi = ap.rssi;
    }
}

bool uplink_wifi_up(void)
{
    return s_events && (xEventGroupGetBits(s_events) & WIFI_CONNECTED_BIT);
}

bool uplink_time_valid(void) { return s_time_valid; }

int uplink_scan(uplink_ap_t *out, int max)
{
    wifi_scan_config_t scan = { .show_hidden = false };
    if (esp_wifi_scan_start(&scan, true) != ESP_OK) return 0;

    uint16_t found = 0;
    esp_wifi_scan_get_ap_num(&found);
    if (found == 0) return 0;
    if (found > 32) found = 32;

    wifi_ap_record_t *records = calloc(found, sizeof(wifi_ap_record_t));
    if (!records) return 0;
    if (esp_wifi_scan_get_ap_records(&found, records) != ESP_OK) {
        free(records);
        return 0;
    }

    int n = 0;
    for (int i = 0; i < found && n < max; i++) {
        if (records[i].ssid[0] == '\0') continue;
        /* The strongest copy of each SSID: a site with three access points on
         * one network should offer one entry, not three. */
        bool seen = false;
        for (int k = 0; k < n; k++)
            if (!strcmp(out[k].ssid, (const char *)records[i].ssid)) { seen = true; break; }
        if (seen) continue;

        strncpy(out[n].ssid, (const char *)records[i].ssid, sizeof(out[n].ssid) - 1);
        out[n].ssid[sizeof(out[n].ssid) - 1] = '\0';
        out[n].rssi = records[i].rssi;
        out[n].secured = (records[i].authmode != WIFI_AUTH_OPEN);
        n++;
    }
    free(records);

    /* Strongest first: on a mine site the list is long and the useful entry is
     * almost always the loudest one. */
    for (int i = 1; i < n; i++) {
        uplink_ap_t key = out[i];
        int j = i - 1;
        while (j >= 0 && out[j].rssi < key.rssi) { out[j + 1] = out[j]; j--; }
        out[j + 1] = key;
    }

    ESP_LOGI(TAG, "scan found %d network(s)", n);
    /* Scanning drops the station link on some builds; get straight back on. */
    if (s_cfg->wifi_ssid[0] && !uplink_wifi_up()) esp_wifi_connect();
    return n;
}

void uplink_wifi_apply(void)
{
    if (!s_cfg->wifi_ssid[0]) return;

    wifi_config_t wc = {0};
    strncpy((char *)wc.sta.ssid, s_cfg->wifi_ssid, sizeof(wc.sta.ssid) - 1);
    strncpy((char *)wc.sta.password, s_cfg->wifi_pass, sizeof(wc.sta.password) - 1);
    wc.sta.threshold.authmode = WIFI_AUTH_OPEN;

    s_wifi_retries = 0;
    esp_wifi_disconnect();
    esp_wifi_set_config(WIFI_IF_STA, &wc);
    esp_wifi_connect();
    ESP_LOGI(TAG, "joining \"%s\" with the credentials just saved", s_cfg->wifi_ssid);

    /* SNTP and MQTT were never started if the gateway booted with no network
     * configured. Start them now that it has one; both calls are idempotent. */
    if (!s_mqtt) mqtt_start();
    sntp_start();
}

/* -------------------------------------------------------------------- SNTP */
/*
 * The gateway is the field's clock. It is the only device with internet, and
 * every node's timestamps -- and therefore every rate the early warning is
 * built on -- are disciplined from here by TIME_SYNC.
 */
static void sntp_ready(struct timeval *tv)
{
    (void)tv;
    s_time_valid = true;
    time_t now = time(NULL);
    ESP_LOGI(TAG, "clock set from NTP: %s", ctime(&now));
}

static void sntp_start(void)
{
    /* Idempotent: this is called at boot when a network is already configured,
     * and again when one is configured later from the web UI. Initialising the
     * SNTP client twice is not harmless. */
    static bool started;
    if (started) return;
    started = true;

    esp_sntp_setoperatingmode(ESP_SNTP_OPMODE_POLL);
    esp_sntp_setservername(0, "pool.ntp.org");
    esp_sntp_setservername(1, "time.google.com");
    sntp_set_time_sync_notification_cb(sntp_ready);
    esp_sntp_init();
}

/* -------------------------------------------------------------------- MQTT */

static void on_mqtt(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg; (void)base;
    esp_mqtt_event_handle_t ev = (esp_mqtt_event_handle_t)data;

    switch ((esp_mqtt_event_id_t)id) {
    case MQTT_EVENT_CONNECTED: {
        s_mqtt_up = true;
        char topic[64];
        snprintf(topic, sizeof(topic), "subnet/gw/%s/cmd", s_cfg->gateway_id);
        esp_mqtt_client_subscribe(s_mqtt, topic, 1);
        /* The backend addresses site-wide downlinks to "all" when it does not
         * know which gateway can reach a node. */
        esp_mqtt_client_subscribe(s_mqtt, "subnet/gw/all/cmd", 1);
        ESP_LOGI(TAG, "MQTT connected; subscribed to %s and subnet/gw/all/cmd", topic);
        break;
    }
    case MQTT_EVENT_DISCONNECTED:
        s_mqtt_up = false;
        ESP_LOGW(TAG, "MQTT disconnected; uplink falls back to HTTP");
        break;
    case MQTT_EVENT_DATA: {
        /* A downlink. It is raw protocol bytes and it came off the network, so
         * it is validated exactly like a frame off the radio before anything is
         * transmitted into the field. */
        subnet_frame_t f;
        subnet_err_t err = subnet_frame_parse((const uint8_t *)ev->data,
                                              (size_t)ev->data_len, &f);
        if (err != SUBNET_OK) {
            ESP_LOGW(TAG, "rejected a downlink: %s", subnet_strerror(err));
            break;
        }
        if (f.type != MSG_CONFIG_SET && f.type != MSG_TIME_SYNC) {
            ESP_LOGW(TAG, "ignoring downlink of type 0x%X", f.type);
            break;
        }
        s_downlinks++;
        if (s_on_downlink) s_on_downlink((const uint8_t *)ev->data, (size_t)ev->data_len);
        break;
    }
    default:
        break;
    }
}

static void mqtt_start(void)
{
    if (!s_cfg->mqtt_host[0]) {
        ESP_LOGI(TAG, "no MQTT host set; using HTTP for both directions");
        return;
    }
    char uri[96];
    snprintf(uri, sizeof(uri), "mqtt://%s:1883", s_cfg->mqtt_host);

    esp_mqtt_client_config_t mc = {
        .broker.address.uri = uri,
        .credentials.client_id = s_cfg->gateway_id,
        .session.keepalive = 60,
    };
    s_mqtt = esp_mqtt_client_init(&mc);
    if (!s_mqtt) return;
    esp_mqtt_client_register_event(s_mqtt, ESP_EVENT_ANY_ID, on_mqtt, NULL);
    esp_mqtt_client_start(s_mqtt);
}

/* ------------------------------------------------------------------ uplink */

static bool post_json(const char *path, const char *body, char *resp, size_t resp_cap)
{
    char url[160];
    snprintf(url, sizeof(url), "%s%s", s_cfg->api_url, path);

    esp_http_client_config_t hc = {
        .url = url,
        .method = body ? HTTP_METHOD_POST : HTTP_METHOD_GET,
        .timeout_ms = HTTP_TIMEOUT_MS,
        .disable_auto_redirect = false,
    };
    esp_http_client_handle_t client = esp_http_client_init(&hc);
    if (!client) return false;

    bool ok = false;
    if (body) {
        esp_http_client_set_header(client, "Content-Type", "application/json");
        esp_http_client_set_post_field(client, body, (int)strlen(body));
    }

    esp_err_t err = esp_http_client_open(client, body ? (int)strlen(body) : 0);
    if (err == ESP_OK) {
        if (body) esp_http_client_write(client, body, (int)strlen(body));
        esp_http_client_fetch_headers(client);
        int status = esp_http_client_get_status_code(client);
        int n = 0;
        if (resp && resp_cap) {
            n = esp_http_client_read(client, resp, (int)resp_cap - 1);
            resp[n > 0 ? n : 0] = '\0';
        }
        ok = (status >= 200 && status < 300);
        if (!ok) ESP_LOGW(TAG, "%s -> HTTP %d %s", path, status, resp ? resp : "");
    } else {
        ESP_LOGW(TAG, "%s: %s", url, esp_err_to_name(err));
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return ok;
}

static bool send_http(const spool_batch_t *b)
{
    char *body = malloc(BODY_CAP);
    if (!body) return false;

    int off = snprintf(body, BODY_CAP, "{\"frames\":[");
    for (int i = 0; i < b->count; i++) {
        unsigned char enc[96];
        size_t enc_len = 0;
        if (mbedtls_base64_encode(enc, sizeof(enc), &enc_len,
                                  b->data[i], b->len[i]) != 0) continue;
        enc[enc_len] = '\0';
        int n = snprintf(body + off, BODY_CAP - off, "%s\"%s\"",
                         i ? "," : "", (char *)enc);
        if (n <= 0 || off + n >= BODY_CAP - 128) break;
        off += n;
    }
    snprintf(body + off, BODY_CAP - off, "],\"gateway\":\"%s\",\"site\":\"%s\"}",
             s_cfg->gateway_id, s_cfg->site_slug);

    char resp[256];
    bool ok = post_json("/api/ingest", body, resp, sizeof(resp));
    free(body);
    return ok;
}

static bool send_mqtt(const spool_batch_t *b)
{
    if (!s_mqtt_up) return false;

    /* Newline-separated base64 -- what backend/app/mqtt.py:_split expects for a
     * batched publish. */
    char *payload = malloc(BODY_CAP);
    if (!payload) return false;
    int off = 0;
    for (int i = 0; i < b->count; i++) {
        unsigned char enc[96];
        size_t enc_len = 0;
        if (mbedtls_base64_encode(enc, sizeof(enc), &enc_len,
                                  b->data[i], b->len[i]) != 0) continue;
        if (off + (int)enc_len + 2 >= BODY_CAP) break;
        memcpy(payload + off, enc, enc_len);
        off += (int)enc_len;
        payload[off++] = '\n';
    }

    char topic[64];
    snprintf(topic, sizeof(topic), "subnet/gw/%s/up", s_cfg->gateway_id);
    /* QoS 1: the broker must acknowledge. At QoS 0 a publish into a broker that
     * is quietly gone looks exactly like a successful uplink, and the spool
     * would be advanced over frames nobody received. */
    int msg = esp_mqtt_client_publish(s_mqtt, topic, payload, off, 1, 0);
    free(payload);
    return msg >= 0;
}

bool uplink_send_batch(const spool_batch_t *b)
{
    if (!b || b->count == 0) return false;
    if (!uplink_wifi_up()) return false;

    bool ok = s_mqtt_up ? send_mqtt(b) : false;
    if (!ok) ok = send_http(b);

    if (ok) s_posted += (uint32_t)b->count;
    else    s_failures++;
    return ok;
}

/* ---------------------------------------------------------------- downlink */

bool uplink_poll_config(uint16_t addr)
{
    if (!uplink_wifi_up() || s_mqtt_up) return false;   /* MQTT pushes instead */

    char path[64];
    snprintf(path, sizeof(path), "/api/nodes/%u/config", (unsigned)addr);

    char *resp = malloc(RESP_CAP);
    if (!resp) return false;
    bool got = post_json(path, NULL, resp, RESP_CAP);
    if (!got) { free(resp); return false; }

    cJSON *root = cJSON_Parse(resp);
    free(resp);
    if (!root) return false;

    bool produced = false;
    cJSON *row = NULL;
    cJSON_ArrayForEach(row, root) {
        const cJSON *status = cJSON_GetObjectItem(row, "status");
        if (!cJSON_IsString(status)) continue;
        /* 'pending' has never been sent; 'sent' went out but was never ACKed --
         * on a field of sleeping nodes the second is the common case and it is
         * exactly the one worth retrying. */
        if (strcmp(status->valuestring, "pending") != 0 &&
            strcmp(status->valuestring, "sent") != 0) continue;

        cfg_t cfg = {0};
#define FIELD(name, dst) do {                                      \
            const cJSON *j = cJSON_GetObjectItem(row, name);       \
            if (cJSON_IsNumber(j)) dst = j->valueint;              \
        } while (0)
        FIELD("cfg_version",            cfg.cfg_version);
        FIELD("sample_interval_s",      cfg.sample_interval_s);
        FIELD("wor_period_ms",          cfg.wor_period_ms);
        FIELD("tx_power_dbm",           cfg.tx_power_dbm);
        FIELD("tilt_alert_mdeg",        cfg.tilt_alert_mdeg);
        FIELD("vib_alert_mg",           cfg.vib_alert_mg);
        FIELD("tilt_rate_alert_mdeg_h", cfg.tilt_rate_alert_mdeg_h);
        FIELD("tilt_offset_pitch",      cfg.tilt_offset_pitch);
        FIELD("tilt_offset_roll",       cfg.tilt_offset_roll);
        FIELD("flags",                  cfg.flags);
#undef FIELD
        cfg.cfg_hash = subnet_cfg_hash(&cfg);

        /* The row carries the hash the backend computed. If the two disagree,
         * the two codecs have drifted apart -- send nothing, and say so, rather
         * than push a config the node will reject and the dashboard will show
         * as mysteriously failing. */
        const cJSON *their_hash = cJSON_GetObjectItem(row, "cfg_hash");
        if (cJSON_IsNumber(their_hash) &&
            (uint16_t)their_hash->valueint != cfg.cfg_hash) {
            ESP_LOGE(TAG, "config hash mismatch for 0x%04X (%04X vs %04X) -- "
                          "firmware and backend codecs disagree", addr,
                     (unsigned)their_hash->valueint, cfg.cfg_hash);
            continue;
        }

        uint8_t frame[SUBNET_MAX_FRAME];
        size_t n = subnet_frame_build(frame, sizeof(frame), MSG_CONFIG_SET,
                                      ADDR_GATEWAY, addr, cfg.cfg_version,
                                      MESH_DEFAULT_TTL, 0, &cfg, sizeof(cfg));
        if (n && s_on_downlink) {
            s_downlinks++;
            s_on_downlink(frame, n);
            produced = true;
        }
        break;      /* newest first: one config per node is enough */
    }
    cJSON_Delete(root);
    return produced;
}

bool uplink_push_json(const char *json)
{
    if (!s_cfg->push_url[0] || !json) return false;
    if (!uplink_wifi_up()) return false;

    esp_http_client_config_t hc = {
        .url = s_cfg->push_url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = HTTP_TIMEOUT_MS,
        /* Certificate bundle rather than a pinned root: this endpoint is
         * whatever the operator typed, and it is a convenience feed, not the
         * path a warning depends on. */
        .crt_bundle_attach = esp_crt_bundle_attach,
    };
    esp_http_client_handle_t client = esp_http_client_init(&hc);
    if (!client) return false;

    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, json, (int)strlen(json));

    bool ok = false;
    esp_err_t err = esp_http_client_perform(client);
    if (err == ESP_OK) {
        int status = esp_http_client_get_status_code(client);
        ok = (status >= 200 && status < 300);
        if (!ok) ESP_LOGW(TAG, "push endpoint answered HTTP %d", status);
    } else {
        ESP_LOGW(TAG, "push to %s failed: %s", s_cfg->push_url, esp_err_to_name(err));
    }
    esp_http_client_cleanup(client);

    if (ok) {
        s_push_ok++;
        s_push_last_ms = (uint32_t)(esp_timer_get_time() / 1000);
    } else {
        s_push_fail++;
    }
    return ok;
}

void uplink_push_stats(uint32_t *ok, uint32_t *failures, uint32_t *last_ms)
{
    if (ok)       *ok = s_push_ok;
    if (failures) *failures = s_push_fail;
    if (last_ms)  *last_ms = s_push_last_ms;
}

void uplink_stats(uint32_t *posted, uint32_t *failures, uint32_t *downlinks)
{
    if (posted)    *posted = s_posted;
    if (failures)  *failures = s_failures;
    if (downlinks) *downlinks = s_downlinks;
}

/* ------------------------------------------------------------------- start */

esp_err_t uplink_start(const nodecfg_t *cfg, uplink_downlink_fn on_downlink)
{
    s_cfg = cfg;
    s_on_downlink = on_downlink;
    s_events = xEventGroupCreate();

    /* Always: the access point half of this is how the gateway is reached when
     * the site network is the thing that is broken. */
    wifi_start();

    if (cfg->wifi_ssid[0]) {
        /* Do not block on the join. The radio side of the gateway must start
         * receiving immediately -- frames arriving while WiFi negotiates are
         * frames the spool would otherwise never see. */
        sntp_start();
        mqtt_start();
    }
    return ESP_OK;
}
