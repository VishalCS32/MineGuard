#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "nvs.h"
#include "nvs_flash.h"

#include "nodecfg.h"
#include "subnet_proto.h"

static const char *TAG = "nodecfg";
static const char *NS  = "subnet";

/* Provisional addresses live at 0x8000 and up. Survey-assigned addresses are
 * handed out from 0x0010, so the two ranges cannot collide and an operator can
 * tell at a glance which nodes still need placing. */
#define PROVISIONAL_BASE 0x8000

static void defaults(nodecfg_t *c)
{
    memset(c, 0, sizeof(*c));
    c->addr        = 0;              /* filled from the MAC below */
    c->role        = NODE_ROLE_NODE;
    c->provisioned = false;
    snprintf(c->label, sizeof(c->label), "unset");

    c->cfg = (cfg_t){
        .cfg_version            = 0,
        .sample_interval_s      = 60,
        .wor_period_ms          = 2000,
        .tx_power_dbm           = 22,
        .tilt_alert_mdeg        = 2000,
        .vib_alert_mg           = 500,
        .tilt_rate_alert_mdeg_h = 150,
        .tilt_offset_pitch      = 0,
        .tilt_offset_roll       = 0,
        .flags = CFG_FLAG_RELAY_ENABLED | CFG_FLAG_GNSS_ENABLED |
                 CFG_FLAG_VIB_ENABLED   | CFG_FLAG_DEEP_SLEEP,
        .cfg_hash = 0,
    };
    c->cfg.cfg_hash = subnet_cfg_hash(&c->cfg);

    snprintf(c->site_slug,  sizeof(c->site_slug),  "jharia");
    snprintf(c->gateway_id, sizeof(c->gateway_id), "gw-01");
    snprintf(c->api_url,    sizeof(c->api_url),    "http://192.168.1.100:8000");
    /* A default, and the firmware complains about it at every boot until it is
     * changed: anyone within WiFi range of this password can reconfigure the
     * gateway and send SMS from it. */
    snprintf(c->ap_pass,    sizeof(c->ap_pass),    "mineguard");
}

uint16_t nodecfg_addr_from_mac(void)
{
    uint8_t mac[6] = {0};
    esp_efuse_mac_get_default(mac);
    uint16_t h = mesh_crc16(mac, sizeof(mac));
    uint16_t addr = (uint16_t)(PROVISIONAL_BASE | (h & 0x7FFF));
    /* 0xFFFF is broadcast; nudge rather than collide. */
    if (addr == ADDR_BROADCAST) addr--;
    return addr;
}

static void get_str(nvs_handle_t h, const char *key, char *dst, size_t cap)
{
    size_t len = cap;
    if (nvs_get_str(h, key, dst, &len) != ESP_OK) return;
    dst[cap - 1] = '\0';
}

void nodecfg_load(nodecfg_t *out)
{
    defaults(out);

    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "NVS needs erasing; doing that now");
        nvs_flash_erase();
        err = nvs_flash_init();
    }
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "NVS unavailable (%s); running on defaults", esp_err_to_name(err));
        out->addr = nodecfg_addr_from_mac();
        return;
    }

    nvs_handle_t h;
    if (nvs_open(NS, NVS_READONLY, &h) != ESP_OK) {
        ESP_LOGW(TAG, "no stored identity; deriving a provisional address from the MAC");
        out->addr = nodecfg_addr_from_mac();
        return;
    }

    uint16_t u16; uint8_t u8;
    if (nvs_get_u16(h, "addr", &u16) == ESP_OK && u16 != ADDR_UNASSIGNED) {
        out->addr = u16;
        out->provisioned = true;
    }
    if (nvs_get_u8(h, "role", &u8) == ESP_OK) out->role = (node_role_t)u8;
    get_str(h, "label", out->label, sizeof(out->label));

    size_t sz = sizeof(cfg_t);
    cfg_t stored;
    if (nvs_get_blob(h, "cfg", &stored, &sz) == ESP_OK && sz == sizeof(cfg_t)) {
        /* A config whose hash does not verify is a config we cannot trust to
         * describe the node's real state -- fall back to defaults rather than
         * run on values that may have been half-written. */
        if (subnet_cfg_valid(&stored)) out->cfg = stored;
        else ESP_LOGW(TAG, "stored config failed its hash; using defaults");
    }

    get_str(h, "wifi_ssid", out->wifi_ssid, sizeof(out->wifi_ssid));
    get_str(h, "wifi_pass", out->wifi_pass, sizeof(out->wifi_pass));
    get_str(h, "api_url",   out->api_url,   sizeof(out->api_url));
    get_str(h, "mqtt",      out->mqtt_host,  sizeof(out->mqtt_host));
    get_str(h, "ap_pass",   out->ap_pass,    sizeof(out->ap_pass));
    get_str(h, "push",      out->push_url,   sizeof(out->push_url));
    get_str(h, "site",      out->site_slug, sizeof(out->site_slug));
    get_str(h, "gw_id",     out->gateway_id, sizeof(out->gateway_id));
    get_str(h, "sms",       out->sms_recipients, sizeof(out->sms_recipients));
    nvs_close(h);

    if (!out->provisioned) {
        out->addr = nodecfg_addr_from_mac();
        ESP_LOGW(TAG, "UNPROVISIONED -- provisional address 0x%04X. "
                      "Set a real one with: set addr 0x0010 / save", out->addr);
    }
}

bool nodecfg_save(const nodecfg_t *c)
{
    nvs_handle_t h;
    if (nvs_open(NS, NVS_READWRITE, &h) != ESP_OK) return false;

    bool ok = nvs_set_u16(h, "addr", c->addr) == ESP_OK
           && nvs_set_u8(h, "role", (uint8_t)c->role) == ESP_OK
           && nvs_set_str(h, "label", c->label) == ESP_OK
           && nvs_set_blob(h, "cfg", &c->cfg, sizeof(cfg_t)) == ESP_OK
           && nvs_set_str(h, "wifi_ssid", c->wifi_ssid) == ESP_OK
           && nvs_set_str(h, "wifi_pass", c->wifi_pass) == ESP_OK
           && nvs_set_str(h, "api_url", c->api_url) == ESP_OK
           && nvs_set_str(h, "mqtt", c->mqtt_host) == ESP_OK
           && nvs_set_str(h, "ap_pass", c->ap_pass) == ESP_OK
           && nvs_set_str(h, "push", c->push_url) == ESP_OK
           && nvs_set_str(h, "site", c->site_slug) == ESP_OK
           && nvs_set_str(h, "gw_id", c->gateway_id) == ESP_OK
           && nvs_set_str(h, "sms", c->sms_recipients) == ESP_OK
           && nvs_commit(h) == ESP_OK;

    nvs_close(h);
    if (ok) ESP_LOGI(TAG, "saved: addr=0x%04X role=%s label=%s",
                     c->addr, c->role == NODE_ROLE_GATEWAY ? "gateway" : "node", c->label);
    return ok;
}

bool nodecfg_factory_reset(void)
{
    nvs_handle_t h;
    if (nvs_open(NS, NVS_READWRITE, &h) != ESP_OK) return false;
    bool ok = nvs_erase_all(h) == ESP_OK && nvs_commit(h) == ESP_OK;
    nvs_close(h);
    return ok;
}

uint8_t nodecfg_apply_downlink(nodecfg_t *c, const cfg_t *incoming)
{
    if (!subnet_cfg_valid(incoming)) {
        ESP_LOGW(TAG, "downlink config failed its hash -- rejected");
        return CFG_STATUS_REJECTED;
    }
    /* Replaying an old version would silently undo a newer setting. Version 0
     * is the factory default and never arrives over the air. */
    if (incoming->cfg_version != 0 && incoming->cfg_version < c->cfg.cfg_version) {
        ESP_LOGW(TAG, "downlink config v%u is older than the running v%u -- rejected",
                 incoming->cfg_version, c->cfg.cfg_version);
        return CFG_STATUS_REJECTED;
    }

    c->cfg = *incoming;
    bool saved = nodecfg_save(c);
    if (!saved) {
        /* It is running, but it will not survive a reboot. Saying "partial" is
         * the honest answer; the dashboard shows it and an operator can retry. */
        ESP_LOGE(TAG, "config applied in RAM but NVS write failed");
        return CFG_STATUS_PARTIAL;
    }
    ESP_LOGI(TAG, "applied config v%u (hash 0x%04X)", c->cfg.cfg_version, c->cfg.cfg_hash);
    return CFG_STATUS_APPLIED;
}

void nodecfg_print(const nodecfg_t *c)
{
    printf("\n-- identity --------------------------------------------------\n");
    printf("  addr        0x%04X %s\n", c->addr,
           c->provisioned ? "(provisioned)" : "(PROVISIONAL, derived from MAC)");
    printf("  role        %s\n", c->role == NODE_ROLE_GATEWAY ? "gateway" : "node");
    printf("  label       %s\n", c->label);
    printf("-- config v%u (hash 0x%04X) ------------------------------------\n",
           c->cfg.cfg_version, c->cfg.cfg_hash);
    printf("  interval    %u s\n", c->cfg.sample_interval_s);
    printf("  wor period  %u ms\n", c->cfg.wor_period_ms);
    printf("  tx power    %u dBm\n", c->cfg.tx_power_dbm);
    printf("  tilt alert  %u mdeg\n", c->cfg.tilt_alert_mdeg);
    printf("  rate alert  %u mdeg/h\n", c->cfg.tilt_rate_alert_mdeg_h);
    printf("  vib alert   %u mg\n", c->cfg.vib_alert_mg);
    printf("  offsets     pitch %d roll %d mdeg\n",
           c->cfg.tilt_offset_pitch, c->cfg.tilt_offset_roll);
    printf("  flags       0x%02X [%s%s%s%s]\n", c->cfg.flags,
           (c->cfg.flags & CFG_FLAG_RELAY_ENABLED) ? "relay " : "",
           (c->cfg.flags & CFG_FLAG_GNSS_ENABLED)  ? "gnss "  : "",
           (c->cfg.flags & CFG_FLAG_VIB_ENABLED)   ? "vib "   : "",
           (c->cfg.flags & CFG_FLAG_DEEP_SLEEP)    ? "sleep"  : "always-on");
    if (c->role == NODE_ROLE_GATEWAY) {
        printf("-- gateway ---------------------------------------------------\n");
        printf("  wifi        %s\n", c->wifi_ssid[0] ? c->wifi_ssid : "(unset)");
        printf("  api         %s\n", c->api_url);
        printf("  mqtt        %s\n", c->mqtt_host[0] ? c->mqtt_host : "(none: HTTP both ways)");
        printf("  push        %s\n", c->push_url[0] ? c->push_url : "(off)");
        printf("  site        %s\n", c->site_slug);
        printf("  gateway id  %s\n", c->gateway_id);
        printf("  sms to      %s\n", c->sms_recipients[0] ? c->sms_recipients : "(none)");
        printf("  ap password %s\n",
               strcmp(c->ap_pass, "mineguard") ? "(set)" : "mineguard  <-- CHANGE THIS");
    }
    printf("--------------------------------------------------------------\n\n");
}
