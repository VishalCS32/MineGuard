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
    /* WPA2 password for the gateway's own access point, which is how a phone
     * reaches the on-site web UI when there is no site network at all. */
    char        ap_pass[NODECFG_LABEL_LEN];
    char        site_slug[NODECFG_LABEL_LEN];
    char        gateway_id[NODECFG_LABEL_LEN];
    char        sms_recipients[NODECFG_STR_LEN];  /* comma-separated E.164   */
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
 *   set site jharia
 *   set sms +911234567890,+919876543210
 *   save                      commit to NVS
 *   reboot
 *   factory                   wipe and reboot
 */
void nodecfg_cli_start(nodecfg_t *cfg);

#endif /* NODECFG_H */
