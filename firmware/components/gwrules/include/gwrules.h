/*
 * The gateway's local rule engine -- the part of the alerting chain that owes
 * nothing to the internet.
 *
 * An SMS that requires the backend to be reachable is an SMS that fails exactly
 * when it is needed: 3 a.m., backhaul down, ground moving. So the gateway makes
 * its own judgement from the frames in front of it and hands a finished message
 * to the SIM800L, with no server in the path.
 *
 * Two sources, deliberately different in how much they are trusted:
 *
 *   EVENT frames      always actionable. The node already applied its own
 *                     thresholds and decided; the gateway only decides whether
 *                     this particular breach is worth a message and whether it
 *                     has already said so.
 *
 *   TELEMETRY frames  only once the uplink has been down for a while. While the
 *                     backend is reachable it is the authority -- it has the
 *                     baselines, the temperature correction and the whole
 *                     array, none of which the gateway has. Judging telemetry
 *                     locally at the same time would produce a second, cruder
 *                     opinion and duplicate texts.
 *
 * No ESP-IDF here either: this decides who gets woken at night, so it is tested
 * on a laptop rather than by taking the site's backhaul down to see what
 * happens.
 */
#ifndef GWRULES_H
#define GWRULES_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "mesh_proto.h"

/* One slot per node in the field, with room to spare for a neighbouring panel's
 * traffic arriving over the mesh. */
#define GWRULES_MAX_NODES   32

/* A single SMS. Longer messages are split by the network into parts that can
 * arrive out of order, so the composer keeps everything inside one. */
#define GWRULES_SMS_LEN     160

typedef struct {
    /* Fallback thresholds, used only while the uplink is down. They mirror the
     * node defaults rather than the backend's tuned values, because the node's
     * are the ones that were pushed to the field. */
    uint16_t tilt_alert_mdeg;
    uint16_t tilt_rate_alert_mdeg_h;
    uint16_t vib_alert_mg;

    uint8_t  min_severity;       /* below this an event is logged, not texted  */
    uint32_t cooldown_s;         /* per node                                   */
    uint32_t link_down_grace_s;  /* how long the uplink must be down before
                                    telemetry-driven rules take over            */
} gwrules_cfg_t;

typedef struct {
    uint16_t addr;
    uint32_t last_sms_epoch;
    uint8_t  last_sev;
    uint16_t last_tilt_mdeg;
    uint32_t last_tilt_epoch;
} gwrules_node_t;

typedef struct {
    gwrules_cfg_t   cfg;
    gwrules_node_t  nodes[GWRULES_MAX_NODES];
    uint32_t        uplink_ok_epoch;   /* last time a batch reached the backend */
    uint32_t        sent, suppressed;
} gwrules_t;

/* Defaults matching the node's shipped configuration. */
gwrules_cfg_t gwrules_default_cfg(void);

void gwrules_init(gwrules_t *g, const gwrules_cfg_t *cfg);

/* Called on every successful uplink. While these keep arriving the gateway
 * defers to the backend for anything it did not already decide. */
void gwrules_note_uplink_ok(gwrules_t *g, uint32_t now_epoch);

/* True when the backend has been unreachable long enough for the gateway to
 * start judging telemetry on its own. */
bool gwrules_link_is_down(const gwrules_t *g, uint32_t now_epoch);

/*
 * Decide on a frame. Returns true and fills `sms` when a message should go out;
 * false when the frame is below threshold, inside a node's cooldown, or (for
 * telemetry) the backend is doing the judging.
 */
bool gwrules_on_event(gwrules_t *g, uint16_t src, const evt_t *e,
                      uint32_t now_epoch, char *sms, size_t cap);

bool gwrules_on_telemetry(gwrules_t *g, uint16_t src, const tlm_t *t,
                          uint32_t now_epoch, char *sms, size_t cap);

/* Short human names, as they appear in the message. */
const char *gwrules_event_name(uint8_t event_code);
const char *gwrules_severity_name(uint8_t severity);

/* Compose without deciding -- used by the CLI's `test-sms` and by the tests. */
void gwrules_compose(char *sms, size_t cap, uint16_t src, uint8_t severity,
                     uint8_t event_code, int32_t value, int32_t threshold);

#endif /* GWRULES_H */
