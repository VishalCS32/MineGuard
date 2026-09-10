#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "esp_timer.h"

#include "fieldview.h"
#include "gwrules.h"
#include "report.h"
#include "statusled.h"
#include "uplink.h"

static nodecfg_t   *s_cfg;
static gw_status_fn s_status;

void report_init(nodecfg_t *cfg, gw_status_fn status)
{
    s_cfg = cfg;
    s_status = status;
}

cJSON *report_status(void)
{
    gw_status_t st = {0};
    if (s_status) s_status(&st);

    uplink_net_t net;
    uplink_netinfo(&net);

    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "gateway", s_cfg->gateway_id);
    cJSON_AddStringToObject(root, "site", s_cfg->site_slug);
    cJSON_AddNumberToObject(root, "addr", s_cfg->addr);
    cJSON_AddNumberToObject(root, "uptime_s", (double)(esp_timer_get_time() / 1000000));
    cJSON_AddBoolToObject(root, "time_valid", uplink_time_valid());
    cJSON_AddNumberToObject(root, "epoch", uplink_time_valid() ? (double)time(NULL) : 0);

    cJSON *wifi = cJSON_AddObjectToObject(root, "wifi");
    cJSON_AddBoolToObject(wifi, "sta_up", net.sta_up);
    cJSON_AddStringToObject(wifi, "sta_ssid", net.sta_ssid);
    cJSON_AddStringToObject(wifi, "sta_ip", net.sta_ip);
    cJSON_AddNumberToObject(wifi, "rssi", net.rssi);
    cJSON_AddStringToObject(wifi, "ap_ssid", net.ap_ssid);
    cJSON_AddStringToObject(wifi, "ap_ip", net.ap_ip);
    cJSON_AddNumberToObject(wifi, "ap_clients", net.ap_clients);

    cJSON *up = cJSON_AddObjectToObject(root, "uplink");
    cJSON_AddStringToObject(up, "transport", s_cfg->mqtt_host[0] ? "mqtt+http" : "http");
    cJSON_AddStringToObject(up, "api", s_cfg->api_url);
    cJSON_AddNumberToObject(up, "posted", st.posted);
    cJSON_AddNumberToObject(up, "failures", st.post_failures);
    cJSON_AddNumberToObject(up, "downlinks", st.downlinks);
    cJSON_AddBoolToObject(up, "link_down", st.link_down);

    cJSON *push = cJSON_AddObjectToObject(root, "push");
    cJSON_AddStringToObject(push, "url", s_cfg->push_url);
    uint32_t ok = 0, fail = 0, last_ms = 0;
    uplink_push_stats(&ok, &fail, &last_ms);
    cJSON_AddNumberToObject(push, "sent", ok);
    cJSON_AddNumberToObject(push, "failures", fail);
    cJSON_AddNumberToObject(push, "last_age_s",
                            last_ms ? (double)(((uint32_t)(esp_timer_get_time() / 1000)
                                                - last_ms) / 1000) : -1);

    cJSON *spool = cJSON_AddObjectToObject(root, "spool");
    cJSON_AddStringToObject(spool, "backing", st.spool_sd ? "microSD" : "RAM");
    cJSON_AddNumberToObject(spool, "depth", st.spool_depth);
    cJSON_AddNumberToObject(spool, "shed", st.spool_shed);

    cJSON *mesh = cJSON_AddObjectToObject(root, "mesh");
    cJSON_AddBoolToObject(mesh, "radio_up", st.radio_up);
    cJSON_AddNumberToObject(mesh, "rx_total", st.rx_total);
    cJSON_AddNumberToObject(mesh, "rx_dup", st.rx_dup);
    cJSON_AddNumberToObject(mesh, "rx_bad", st.rx_bad);
    cJSON_AddNumberToObject(mesh, "relayed", st.relayed);
    cJSON_AddNumberToObject(mesh, "tx", st.tx_count);
    cJSON_AddNumberToObject(mesh, "crc_err", st.crc_err);

    cJSON *sms = cJSON_AddObjectToObject(root, "sms");
    cJSON_AddBoolToObject(sms, "modem", st.modem_ready);
    cJSON_AddBoolToObject(sms, "registered", st.modem_registered);
    cJSON_AddNumberToObject(sms, "csq", st.modem_csq);
    cJSON_AddNumberToObject(sms, "sent", st.sms_sent);
    cJSON_AddNumberToObject(sms, "suppressed", st.sms_suppressed);
    cJSON_AddStringToObject(sms, "recipients", s_cfg->sms_recipients);

    /* What the LED on the box is doing, and what it means. Somebody reading a
     * blink count in the dark can then have this page tell them what they are
     * looking at, instead of finding the manual. */
    statusled_code_t led = statusled_current();
    cJSON *led_obj = cJSON_AddObjectToObject(root, "led");
    cJSON_AddStringToObject(led_obj, "code", statusled_tag(led));
    cJSON_AddNumberToObject(led_obj, "blinks", statusled_blinks(led));
    cJSON_AddStringToObject(led_obj, "meaning", statusled_meaning(led));

    cJSON_AddNumberToObject(root, "vbat_mv", st.vbat_mv);
    return root;
}

cJSON *report_nodes(void)
{
    uint32_t now_ms = (uint32_t)(esp_timer_get_time() / 1000);

    cJSON *root = cJSON_CreateObject();
    cJSON *arr = cJSON_AddArrayToObject(root, "nodes");

    fieldview_node_t n;
    for (int i = 0; fieldview_get(i, &n); i++) {
        cJSON *o = cJSON_CreateObject();
        cJSON_AddNumberToObject(o, "addr", n.addr);
        cJSON_AddNumberToObject(o, "age_s", (double)((now_ms - n.last_ms) / 1000));
        cJSON_AddNumberToObject(o, "frames", n.frames);
        cJSON_AddNumberToObject(o, "rssi", n.rssi);
        /* Back to decibels: the frame carries (dB + 20) * 4 so that it fits a
         * byte, and nobody reads it in those units. */
        cJSON_AddNumberToObject(o, "snr_db", (n.snr / 4.0) - 20.0);
        cJSON_AddNumberToObject(o, "hops", n.hops);
        cJSON_AddBoolToObject(o, "have_tlm", n.have_tlm);
        if (n.have_tlm) {
            cJSON_AddNumberToObject(o, "t_epoch", n.tlm_epoch);
            cJSON_AddNumberToObject(o, "pitch_mdeg", n.pitch_mdeg);
            cJSON_AddNumberToObject(o, "roll_mdeg", n.roll_mdeg);
            cJSON_AddNumberToObject(o, "vib_rms_mg", n.vib_rms_mg);
            cJSON_AddNumberToObject(o, "temp_c", n.temp_c_x100 / 100.0);
            cJSON_AddNumberToObject(o, "vbat_mv", n.vbat_mv);
            cJSON_AddNumberToObject(o, "flags", n.flags);
            cJSON_AddNumberToObject(o, "fix", n.gnss_status & 0x03);
            cJSON_AddNumberToObject(o, "sats", (n.gnss_status >> 2) & 0x3F);
        }
        if (n.last_evt_epoch) {
            cJSON_AddStringToObject(o, "event", gwrules_event_name(n.last_evt_code));
            cJSON_AddNumberToObject(o, "event_sev", n.last_evt_sev);
            cJSON_AddNumberToObject(o, "event_epoch", n.last_evt_epoch);
        }
        cJSON_AddItemToArray(arr, o);
    }
    return root;
}

char *report_push_document(void)
{
    cJSON *root = report_status();
    cJSON *nodes = report_nodes();

    /* Move the array across rather than nesting the wrapper object, so the
     * document reads as {gateway, site, ..., nodes:[...]}. */
    cJSON *arr = cJSON_DetachItemFromObject(nodes, "nodes");
    cJSON_Delete(nodes);
    if (arr) cJSON_AddItemToObject(root, "nodes", arr);

    char *text = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return text;
}
