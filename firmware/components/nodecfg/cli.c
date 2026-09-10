/*
 * USB-serial provisioning console.
 *
 * Deliberately line-oriented and boring: every command is one line of plain
 * ASCII with a one-line reply, so a human on a laptop and tools/provision.py
 * driving 21 boards in sequence speak exactly the same protocol. Replies start
 * with "OK" or "ERR" so the script can tell what happened without parsing prose.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "nodecfg.h"
#include "subnet_proto.h"

static const char *TAG = "cli";
static nodecfg_t *g_cfg;

#define CLI_LINE_MAX 160   /* not LINE_MAX: that is POSIX's, in limits.h */

static void copy_arg(char *dst, size_t cap, const char *src)
{
    strncpy(dst, src, cap - 1);
    dst[cap - 1] = '\0';
}

/* Accepts 0x-prefixed hex or plain decimal, so `set addr 0x0014` and
 * `set addr 20` both work and neither surprises anyone. */
static bool parse_u32(const char *s, uint32_t *out)
{
    char *end = NULL;
    unsigned long v = strtoul(s, &end, (strncmp(s, "0x", 2) == 0 || strncmp(s, "0X", 2) == 0) ? 16 : 10);
    if (end == s || *end != '\0') return false;
    *out = (uint32_t)v;
    return true;
}

static void rehash(nodecfg_t *c)
{
    /* Any local edit invalidates the backend's version number: this config no
     * longer describes what the dashboard pushed, and pretending otherwise would
     * make the UI show a config the node is not running. */
    c->cfg.cfg_version = 0;
    c->cfg.cfg_hash = subnet_cfg_hash(&c->cfg);
}

static void cmd_help(void)
{
    printf(
      "\ncommands\n"
      "  show                     identity, config, counters\n"
      "  set addr <0x0014|20>     mesh address (0x0010+ = surveyed)\n"
      "  set label <text>\n"
      "  set role node|gateway\n"
      "  set interval <s>         sample interval, 5..3600\n"
      "  set tilt-alert <mdeg>    node-side absolute tilt trigger\n"
      "  set rate-alert <mdeg/h>  node-side tilt RATE trigger (the precursor)\n"
      "  set vib-alert <mg>\n"
      "  set tx-power <10..22>\n"
      "  set wor <ms>             wake-on-radio listen cadence\n"
      "  set flags <0x0F>         bit0 relay, bit1 gnss, bit2 vib, bit3 deep-sleep\n"
      "  set offsets <pitch> <roll>   tilt zero-offset, mdeg\n"
      "  set wifi <ssid> <pass>   gateway\n"
      "  set api <url>            gateway\n"
      "  set mqtt <host|->        gateway; - clears it, back to HTTP\n"
      "  set site <slug>          gateway\n"
      "  set gw-id <id>           gateway\n"
      "  set sms <+91...,+91...>  gateway\n"
      "  set ap-pass <8+ chars>   gateway; guards the on-site web UI\n"
      "  set push <url|->         gateway; realtime JSON push endpoint\n"
      "  save | reboot | factory\n\n");
}

static bool handle_set(char *args)
{
    char *key = strtok(args, " \t");
    char *val = strtok(NULL, " \t");
    if (!key || !val) { printf("ERR set needs a key and a value\n"); return false; }

    uint32_t n;
    nodecfg_t *c = g_cfg;

    if (!strcmp(key, "addr")) {
        if (!parse_u32(val, &n) || n == ADDR_UNASSIGNED || n >= ADDR_BROADCAST) {
            printf("ERR addr must be 0x0001..0xFFFE\n"); return false;
        }
        if (n == ADDR_GATEWAY && c->role != NODE_ROLE_GATEWAY)
            printf("note: 0x0001 is the gateway address; set role gateway too\n");
        c->addr = (uint16_t)n;
        c->provisioned = true;
    } else if (!strcmp(key, "label")) {
        copy_arg(c->label, sizeof(c->label), val);
    } else if (!strcmp(key, "role")) {
        if (!strcmp(val, "gateway")) c->role = NODE_ROLE_GATEWAY;
        else if (!strcmp(val, "node")) c->role = NODE_ROLE_NODE;
        else { printf("ERR role is node or gateway\n"); return false; }
    } else if (!strcmp(key, "interval")) {
        if (!parse_u32(val, &n) || n < 5 || n > 3600) {
            printf("ERR interval is 5..3600 s\n"); return false;
        }
        c->cfg.sample_interval_s = (uint16_t)n; rehash(c);
    } else if (!strcmp(key, "tilt-alert")) {
        if (!parse_u32(val, &n) || n > 32000) { printf("ERR 10..32000 mdeg\n"); return false; }
        c->cfg.tilt_alert_mdeg = (uint16_t)n; rehash(c);
    } else if (!strcmp(key, "rate-alert")) {
        if (!parse_u32(val, &n) || n > 60000) { printf("ERR 1..60000 mdeg/h\n"); return false; }
        c->cfg.tilt_rate_alert_mdeg_h = (uint16_t)n; rehash(c);
    } else if (!strcmp(key, "vib-alert")) {
        if (!parse_u32(val, &n) || n > 60000) { printf("ERR 10..60000 mg\n"); return false; }
        c->cfg.vib_alert_mg = (uint16_t)n; rehash(c);
    } else if (!strcmp(key, "tx-power")) {
        if (!parse_u32(val, &n) || n < 10 || n > 22) { printf("ERR 10..22 dBm\n"); return false; }
        c->cfg.tx_power_dbm = (uint8_t)n; rehash(c);
    } else if (!strcmp(key, "wor")) {
        if (!parse_u32(val, &n) || n < 250 || n > 10000) { printf("ERR 250..10000 ms\n"); return false; }
        c->cfg.wor_period_ms = (uint16_t)n; rehash(c);
    } else if (!strcmp(key, "flags")) {
        if (!parse_u32(val, &n) || n > 255) { printf("ERR 0..255\n"); return false; }
        c->cfg.flags = (uint8_t)n; rehash(c);
    } else if (!strcmp(key, "offsets")) {
        char *second = strtok(NULL, " \t");
        if (!second) { printf("ERR offsets needs pitch and roll\n"); return false; }
        c->cfg.tilt_offset_pitch = (int16_t)atoi(val);
        c->cfg.tilt_offset_roll  = (int16_t)atoi(second);
        rehash(c);
    } else if (!strcmp(key, "wifi")) {
        char *pass = strtok(NULL, "");     /* rest of line: passwords hold spaces */
        copy_arg(c->wifi_ssid, sizeof(c->wifi_ssid), val);
        copy_arg(c->wifi_pass, sizeof(c->wifi_pass), pass ? pass : "");
    } else if (!strcmp(key, "api")) {
        copy_arg(c->api_url, sizeof(c->api_url), val);
    } else if (!strcmp(key, "mqtt")) {
        /* "-" clears it, which is how a site moves back to HTTP without a
         * factory reset. */
        copy_arg(c->mqtt_host, sizeof(c->mqtt_host), strcmp(val, "-") ? val : "");
    } else if (!strcmp(key, "site")) {
        copy_arg(c->site_slug, sizeof(c->site_slug), val);
    } else if (!strcmp(key, "gw-id")) {
        copy_arg(c->gateway_id, sizeof(c->gateway_id), val);
    } else if (!strcmp(key, "push")) {
        copy_arg(c->push_url, sizeof(c->push_url), strcmp(val, "-") ? val : "");
    } else if (!strcmp(key, "ap-pass")) {
        if (strlen(val) < 8) { printf("ERR WPA2 needs 8 characters or more\n"); return false; }
        copy_arg(c->ap_pass, sizeof(c->ap_pass), val);
    } else if (!strcmp(key, "sms")) {
        copy_arg(c->sms_recipients, sizeof(c->sms_recipients), val);
    } else {
        printf("ERR unknown key '%s'\n", key);
        return false;
    }
    printf("OK %s\n", key);
    return true;
}

static void handle_line(char *line)
{
    while (*line == ' ' || *line == '\t') line++;
    if (!*line || *line == '#') return;

    char *cmd = strtok(line, " \t");
    if (!cmd) return;

    if (!strcmp(cmd, "help") || !strcmp(cmd, "?")) {
        cmd_help();
    } else if (!strcmp(cmd, "show")) {
        nodecfg_print(g_cfg);
        printf("OK show\n");
    } else if (!strcmp(cmd, "set")) {
        char *rest = strtok(NULL, "");
        if (!rest) { printf("ERR set what?\n"); return; }
        handle_set(rest);
    } else if (!strcmp(cmd, "save")) {
        printf(nodecfg_save(g_cfg) ? "OK saved\n" : "ERR nvs write failed\n");
    } else if (!strcmp(cmd, "reboot")) {
        printf("OK rebooting\n");
        fflush(stdout);
        vTaskDelay(pdMS_TO_TICKS(200));
        esp_restart();
    } else if (!strcmp(cmd, "factory")) {
        printf(nodecfg_factory_reset() ? "OK wiped, rebooting\n" : "ERR wipe failed\n");
        fflush(stdout);
        vTaskDelay(pdMS_TO_TICKS(200));
        esp_restart();
    } else {
        printf("ERR unknown command '%s' -- try help\n", cmd);
    }
}

static void cli_task(void *arg)
{
    (void)arg;
    char line[CLI_LINE_MAX];
    size_t len = 0;

    printf("\nSUBSIDENCE-NET console. `help` for commands, `show` for state.\n");
    printf("addr=0x%04X role=%s %s\n\n", g_cfg->addr,
           g_cfg->role == NODE_ROLE_GATEWAY ? "gateway" : "node",
           g_cfg->provisioned ? "" : "[UNPROVISIONED]");

    for (;;) {
        int ch = getchar();
        if (ch == EOF) { vTaskDelay(pdMS_TO_TICKS(20)); continue; }
        if (ch == '\r') continue;
        if (ch == '\n') {
            line[len] = '\0';
            handle_line(line);
            len = 0;
            continue;
        }
        if (ch == '\b' || ch == 0x7F) { if (len) len--; continue; }
        if (len < sizeof(line) - 1) line[len++] = (char)ch;
    }
}

void nodecfg_cli_start(nodecfg_t *cfg)
{
    g_cfg = cfg;
    /* Small stack: this task does string handling and nothing else. It runs at
     * a low priority so provisioning chatter can never delay a radio deadline. */
    if (xTaskCreate(cli_task, "cli", 4096, NULL, 2, NULL) != pdPASS)
        ESP_LOGE(TAG, "could not start the console task");
}
