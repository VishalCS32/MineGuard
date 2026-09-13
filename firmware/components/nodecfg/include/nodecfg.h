/*
 * Node identity and runtime configuration, persisted in NVS.
 *
 * THE POINT OF THIS FILE: one firmware binary flashes to every board in the
 * field. What makes a board node 0x0014 rather than node 0x0011 is a value in
 * NVS, set once over the USB serial console (or in bulk by tools/provision.py),
 * never a compile-time constant. Twenty-one boards each needing their own build
 * is twenty-one chances to flash the wrong one, and no way to tell afterwards.
 *
 * Three layers, in priority order:
 *   1. NVS               -- what an operator or the provisioning tool wrote
 *   2. CONFIG_SET downlink -- what the backend has since pushed, ACKed and saved
 *   3. compiled defaults -- what an unprovisioned board falls back to
 *
 * An unprovisioned board still joins: it derives a provisional address from its
 * own MAC and reports. The backend auto-provisions it unplaced, which is how a
 * board that was flashed and dropped in a bag still shows up on the dashboard
 * instead of vanishing.
 */
#ifndef NODECFG_H
#define NODECFG_H

#include <stdbool.h>
#include <stdint.h>

#include "mesh_proto.h"

#define NODECFG_LABEL_LEN 16
#define NODECFG_STR_LEN   64
/* Bearer tokens are generated, not typed, and the hosts that generate them
 * are not shy: Render's are 40+ characters and Railway's longer. Sized so a
 * token is never silently truncated into one that will simply 401. */
#define NODECFG_TOKEN_LEN 128

typedef enum {
    NODE_ROLE_NODE = 0,
    NODE_ROLE_GATEWAY = 1,
} node_role_t;

typedef struct {
    /* -- identity, set at provisioning ------------------------------------ */
    uint16_t    addr;
    node_role_t role;
    char        label[NODECFG_LABEL_LEN];
    bool        provisioned;      /* false => addr was derived from the MAC   */

    /* -- runtime config, pushed by CONFIG_SET and persisted --------------- */
    cfg_t       cfg;

    /* -- gateway only ----------------------------------------------------- */
    char        wifi_ssid[NODECFG_STR_LEN];
    char        wifi_pass[NODECFG_STR_LEN];
    char        api_url[NODECFG_STR_LEN];   /* e.g. http://10.0.0.5:8000     */
    /* Broker for the deployed shape. Empty means HTTP for both directions --
     * losing the broker degrades the transport, never the system. */
    char        mqtt_host[NODECFG_STR_LEN];
    /* Optional realtime push endpoint: the gateway POSTs a decoded JSON
     * document of itself and every node it has heard, on an interval. Separate
     * from api_url on purpose -- that one takes raw protocol frames and is the
     * system of record; this one is for anything else that wants the data and
     * has no copy of the codec. */
    char        push_url[NODECFG_STR_LEN];
    /* Sent as `Authorization: Bearer <token>` on the realtime push, and
     * nowhere else. An ingest endpoint on the public internet without one is
     * a database anyone can fill, and fabricated telemetry is worse than none
     * -- it still draws a line on the chart. Empty means no header, which is
     * right for a receiver on a private network. */
    char        push_token[NODECFG_TOKEN_LEN];
    /* WPA2 password for the gateway's own access point, which is how a phone
     * reaches the on-site web UI when there is no site network at all. */
    char        ap_pass[NODECFG_LABEL_LEN];
    char        site_slug[NODECFG_LABEL_LEN];
    char        gateway_id[NODECFG_LABEL_LEN];
    char        sms_recipients[NODECFG_STR_LEN];  /* comma-separated E.164   */
    /* Which GPIO the onboard RGB pixel is on. 0 means "the board default",
     * PIN_RGB_LED. It is here rather than only in board_pins.h because the
     * pin genuinely differs between otherwise identical S3 mini boards and
     * cannot be probed for -- and a spare gateway that needs a rebuild to
     * show its status is a spare gateway nobody swaps in at night. */
    uint8_t     led_gpio;
    /* 0 = GRB, the near-universal WS2812 order; 1 = RGB, for the parts that
     * are not. Wrong order swaps red and green, which is worse than a dark
     * pixel: the indicator confidently reports the wrong severity. */
    uint8_t     led_order_rgb;
} nodecfg_t;

/* Load from NVS, filling anything unset with defaults. Never fails: a board with
 * a corrupt or empty NVS boots with defaults and says so, because a node that
 * refuses to boot reports nothing at all. */
void nodecfg_load(nodecfg_t *out);

/* Persist. Returns false if NVS rejected the write. */
bool nodecfg_save(const nodecfg_t *cfg);

/* Wipe identity and config back to defaults. */
bool nodecfg_factory_reset(void);

/* Apply a CONFIG_SET received over the air. Verifies the hash before storing --
 * a config corrupted in flight must be rejected, not applied and ACKed.
 * Returns one of CFG_STATUS_*. */
uint8_t nodecfg_apply_downlink(nodecfg_t *cfg, const cfg_t *incoming);

/* Provisional address from the factory MAC, for a board nobody has provisioned.
 * Deterministic, so the same board keeps the same address across reboots, and
 * confined to a high range that a human-assigned address will never collide
 * with. */
uint16_t nodecfg_addr_from_mac(void);

/* Human-readable dump, used by the CLI's `show`. */
void nodecfg_print(const nodecfg_t *cfg);

/*
 * Start the USB-serial console. Non-blocking; runs its own task.
 *
 * Commands (also what tools/provision.py speaks):
 *   show                      print identity, config and radio counters
 *   set addr 0x0014           mesh address
 *   set label T-05
 *   set role node|gateway
 *   set interval 60           sample interval, seconds
 *   set tilt-alert 2000       node-side absolute tilt trigger, mdeg
 *   set rate-alert 150        node-side tilt-RATE trigger, mdeg/h
 *   set vib-alert 500
 *   set flags 0x0F            relay|gnss|vib|deep_sleep
 *   set wifi <ssid> <pass>    gateway only
 *   set api http://host:8000  gateway only
 *   set mqtt 10.0.0.5          gateway only; empty = HTTP both ways
 *   set ap-pass <8+ chars>     gateway only; guards the on-site web UI
 *   set push https://host/hook gateway only; realtime JSON push, '-' clears
 *   set push-token <tok|->     gateway only; bearer token for that endpoint
 *   set site jharia
 *   set sms +911234567890,+919876543210
 *   set led-pin 21            gateway only; onboard RGB pixel, '-' = default
 *   set led-order grb|rgb     byte order, if red and green come out swapped
 *   rftest [dst] [n] [pad]    RF link test -- see components/rftest
 *   gnsstest [seconds]        raw NMEA from the receiver; node only
 *   modemtest                 AT across every baud rate; gateway only
 *   save                      commit to NVS
 *   reboot
 *   factory                   wipe and reboot
 */
/*
 * What the console can ask the application to do. The console lives in a
 * component and the radio lives in the application, so anything that has to
 * touch hardware arrives as a hook rather than as a dependency pointing the
 * wrong way.
 */
typedef struct {
    /*
     * Run an RF link test against `dst` and print the result. Blocking: it
     * runs on the console task, for as long as `count` round trips take.
     * Returns false if it could not run at all -- no radio.
     */
    bool (*rftest)(uint16_t dst, uint16_t count, uint8_t pad);

    /*
     * Dump raw GNSS bytes for `seconds`, to separate "nothing on the wire"
     * from "no fix yet" -- the two look identical from the outside and only
     * one of them is about the sky. Node only; NULL on a gateway.
     */
    bool (*gnsstest)(uint32_t seconds);

    /*
     * Sweep AT across the plausible baud rates and print what comes back, to
     * separate a dead link from a rate mismatch from a dead part. Gateway
     * only; NULL on a node.
     */
    bool (*modemtest)(void);
} nodecfg_hooks_t;

/* `hooks` may be NULL, and any member of it may be NULL: the console then
 * says the command is unavailable rather than crashing on a boot path where
 * the radio never came up. */
void nodecfg_cli_start(nodecfg_t *cfg, const nodecfg_hooks_t *hooks);

#endif /* NODECFG_H */
