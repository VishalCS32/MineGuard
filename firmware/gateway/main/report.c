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
    /* The colour too, so the chip on the page is the colour of the light on
     * the box -- with an RGB indicator the hue carries half the message, and a
     * page that reported only the count would throw that half away. */
    char led_hex[8];
    statusled_colour_hex(led, led_hex, sizeof(led_hex));
    cJSON_AddStringToObject(led_obj, "colour", led_hex);
    cJSON_AddNumberToObject(led_obj, "gpio", (int)statusled_pin());

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

/*
 * One node, in the upstream API's schema.
 *
 * WHERE THIS SCHEMA AND THIS HARDWARE DISAGREE, and what is done about it.
 *
 * The schema describes a richer instrument than a node actually is, and the
 * honest response to a field we cannot measure is `null` -- not 0.0. A zero
 * in `gyro.x` is a claim: it says the node measured rotation and found none.
 * A null says nobody asked. On a system whose whole job is to notice small
 * movements, a fabricated "perfectly still" is the single worst value we
 * could send, because it is indistinguishable from a good reading.
 *
 *   gyro           there is no gyroscope on the board. A LIS3DH is a
 *                  three-axis accelerometer and nothing else. Null, always.
 *   accelerometer  measured on the node, but not transmitted: the frame
 *                  carries the derived pitch/roll instead, because 52 bytes
 *                  of payload does not stretch to raw axes at 22 dBm. The
 *                  gravity vector could be reconstructed from orientation,
 *                  and is not -- that would be arithmetic dressed as a
 *                  measurement, and it would round-trip its own input.
 *   vibration xyz  same: the node computes RMS over a 32-sample burst and
 *                  sends the scalar. Per-axis never leaves the node. `rms`
 *                  is real and is populated.
 *   hdop           the receiver reports a horizontal accuracy estimate in
 *                  centimetres, which is not HDOP and does not convert to
 *                  it -- HDOP is a geometry factor, metres are a result.
 *                  Null, with the real figure alongside as `h_acc_m`.
 *
 * Everything else is measured and is real.
 */
char *report_node_api_document(int index)
{
    fieldview_node_t n;
    if (!fieldview_get(index, &n)) return NULL;

    cJSON *root = cJSON_CreateObject();

    /*
     * The operator's name for this node if one is set, else the address.
     *
     * The address-derived form is the better identity -- unique, stable, and
     * the same thing the frame backend calls the node -- but it is not what
     * anything downstream was written against, and renumbering an installed
     * field to satisfy a dashboard is the wrong way round. See
     * `set node-alias`.
     */
    char node_id[16];
    const char *alias = nodecfg_alias(s_cfg, n.addr);
    if (alias) snprintf(node_id, sizeof(node_id), "%s", alias);
    else       snprintf(node_id, sizeof(node_id), "NODE-%04X", n.addr);
    cJSON_AddStringToObject(root, "node_id", node_id);

    /* The node's own clock where it had one. A node that has never had a
     * TIME_SYNC stamps zero, and rather than relabel that as now -- which
     * would silently claim a precision the reading does not have -- we fall
     * back to the gateway's clock and let `stamped_by` say which it was. */
    uint32_t epoch = n.have_tlm && n.tlm_epoch ? n.tlm_epoch
                   : uplink_time_valid()         ? (uint32_t)time(NULL)
                                                 : 0;
    char iso[32] = "";
    if (epoch) {
        time_t t = (time_t)epoch;
        struct tm tm;
        gmtime_r(&t, &tm);
        strftime(iso, sizeof(iso), "%Y-%m-%dT%H:%M:%SZ", &tm);
    }
    cJSON_AddStringToObject(root, "timestamp", iso);
    cJSON_AddStringToObject(root, "stamped_by",
                            (n.have_tlm && n.tlm_epoch) ? "node" : "gateway");

    cJSON *sd = cJSON_AddObjectToObject(root, "sensor_data");

    /* No gyroscope exists on this hardware. */
    cJSON *gyro = cJSON_AddObjectToObject(sd, "gyro");
    cJSON_AddNullToObject(gyro, "x");
    cJSON_AddNullToObject(gyro, "y");
    cJSON_AddNullToObject(gyro, "z");
    cJSON_AddStringToObject(gyro, "unit", "deg/s");

    /* Measured, but not carried over the air -- see the note above. */
    cJSON *acc = cJSON_AddObjectToObject(sd, "accelerometer");
    cJSON_AddNullToObject(acc, "x");
    cJSON_AddNullToObject(acc, "y");
    cJSON_AddNullToObject(acc, "z");
    cJSON_AddStringToObject(acc, "unit", "m/s^2");

    cJSON *ori = cJSON_AddObjectToObject(sd, "orientation");
    if (n.have_tlm) {
        cJSON_AddNumberToObject(ori, "roll",  n.roll_mdeg / 1000.0);
        cJSON_AddNumberToObject(ori, "pitch", n.pitch_mdeg / 1000.0);
    } else {
        cJSON_AddNullToObject(ori, "roll");
        cJSON_AddNullToObject(ori, "pitch");
    }
    cJSON_AddStringToObject(ori, "unit", "deg");

    cJSON *vib = cJSON_AddObjectToObject(sd, "vibration");
    cJSON_AddNullToObject(vib, "x");
    cJSON_AddNullToObject(vib, "y");
    cJSON_AddNullToObject(vib, "z");
    if (n.have_tlm)
        /* Milli-g on the wire; the schema wants m/s^2. */
        cJSON_AddNumberToObject(vib, "rms", n.vib_rms_mg * 9.80665 / 1000.0);
    else
        cJSON_AddNullToObject(vib, "rms");
    cJSON_AddStringToObject(vib, "unit", "m/s^2");

    if (n.have_tlm) {
        cJSON_AddNumberToObject(sd, "temperature_c", n.temp_c_x100 / 100.0);
        cJSON_AddNumberToObject(sd, "battery_mv", n.vbat_mv);
    } else {
        cJSON_AddNullToObject(sd, "temperature_c");
        cJSON_AddNullToObject(sd, "battery_mv");
    }

    cJSON *gps = cJSON_AddObjectToObject(root, "gps");
    if (n.have_pos) {
        cJSON_AddNumberToObject(gps, "latitude",  n.lat_e7 / 1e7);
        cJSON_AddNumberToObject(gps, "longitude", n.lon_e7 / 1e7);
        cJSON_AddNumberToObject(gps, "altitude",  n.alt_m);
        cJSON_AddNumberToObject(gps, "h_acc_m",   n.h_acc_cm / 100.0);
    } else {
        cJSON_AddNullToObject(gps, "latitude");
        cJSON_AddNullToObject(gps, "longitude");
        cJSON_AddNullToObject(gps, "altitude");
        cJSON_AddNullToObject(gps, "h_acc_m");
    }
    /* Satellite count rides in every telemetry frame, so it is current even
     * when the last actual fix is hours old. */
    if (n.have_tlm) cJSON_AddNumberToObject(gps, "satellites", GNSS_SATS_OF(n.gnss_status));
    else            cJSON_AddNullToObject(gps, "satellites");
    cJSON_AddNullToObject(gps, "hdop");     /* not measured; see h_acc_m */

    cJSON *comm = cJSON_AddObjectToObject(root, "communication");
    cJSON_AddNumberToObject(comm, "rssi_dbm", n.rssi);
    cJSON_AddNumberToObject(comm, "snr_db", (n.snr / 4.0) - 20.0);

    cJSON_AddNumberToObject(root, "flags", n.have_tlm ? n.flags : 0);

    char *text = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return text;
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
