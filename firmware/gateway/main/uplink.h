/*
 * The gateway's network side: WiFi, the clock, the uplink and the downlink.
 *
 * Two transports, both first class, and the choice between them is
 * configuration rather than architecture:
 *
 *   HTTP   POST /api/ingest with base64 frames. The default, and the simplest
 *          thing a constrained ESP32 can do reliably.
 *   MQTT   publish subnet/gw/<id>/up, subscribe subnet/gw/<id>/cmd. What a
 *          deployed site uses, and the only path the backend can push a config
 *          downlink over without being asked.
 *
 * Losing the broker degrades the transport, never the system: with no MQTT host
 * configured everything runs over HTTP, and downlinks are pulled rather than
 * pushed. Losing the WAN degrades it further and still not fatally -- the spool
 * keeps the frames and the local rule engine keeps sending SMS.
 */
#ifndef UPLINK_H
#define UPLINK_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "nodecfg.h"
#include "spool.h"

/* Called with a complete, already-validated downlink frame to be transmitted
 * into the mesh. */
typedef void (*uplink_downlink_fn)(const uint8_t *frame, size_t len);

esp_err_t uplink_start(const nodecfg_t *cfg, uplink_downlink_fn on_downlink);

bool uplink_wifi_up(void);
bool uplink_time_valid(void);

/* What the network looks like right now, for the on-site web UI's header. */
typedef struct {
    bool sta_up;
    char sta_ip[16];
    char sta_ssid[33];
    int  rssi;
    char ap_ssid[33];
    char ap_ip[16];
    int  ap_clients;
} uplink_net_t;

void uplink_netinfo(uplink_net_t *out);

/*
 * Scan for networks in range, so a person on the gateway's own access point can
 * pick the site's WiFi from a list instead of typing an SSID they may be
 * guessing at. Blocking, a couple of seconds, and it briefly costs the station
 * link -- which is acceptable for something a human asked for.
 */
typedef struct {
    char ssid[33];
    int  rssi;
    bool secured;
} uplink_ap_t;

int uplink_scan(uplink_ap_t *out, int max);

/*
 * Re-read the credentials in the config and join, without a reboot. The web UI
 * calls this the moment new credentials are saved: making somebody power-cycle
 * a gateway on a pole to test a password is not a design, it is a punishment.
 */
void uplink_wifi_apply(void);

/*
 * POST a JSON document to the configured realtime push endpoint. Fire and
 * forget by design: this is a convenience feed, and it must never be able to
 * delay or block the frame path that the actual warnings travel on.
 */
bool uplink_push_json(const char *json);
void uplink_push_stats(uint32_t *ok, uint32_t *failures, uint32_t *last_ms);

/* Deliver a batch. Returns true only when the backend has taken responsibility
 * for it -- the spool is not advanced on anything less. */
bool uplink_send_batch(const spool_batch_t *batch);

/*
 * Pull pending configuration for one node over HTTP, for deployments with no
 * broker. Returns true when a downlink was produced and handed to the callback.
 *
 * MQTT gets this for free by subscription; without it the gateway has to ask,
 * and it asks about one node per call so a field of twenty-one nodes costs one
 * small request every few seconds rather than twenty-one at once.
 */
bool uplink_poll_config(uint16_t addr);

/* Counters, printed by the console's `show`. */
void uplink_stats(uint32_t *posted, uint32_t *failures, uint32_t *downlinks);

#endif /* UPLINK_H */
