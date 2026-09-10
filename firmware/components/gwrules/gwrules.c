#include <stdio.h>
#include <string.h>

#include "gwrules.h"

gwrules_cfg_t gwrules_default_cfg(void)
{
    return (gwrules_cfg_t){
        .tilt_alert_mdeg        = 2000,
        .tilt_rate_alert_mdeg_h = 150,
        .vib_alert_mg           = 500,
        /* Severity 2 and above. A severity-1 event is a node noting something;
         * texting a shift in-charge about it teaches them to ignore the next
         * one, which is the failure mode that matters. */
        .min_severity           = 2,
        .cooldown_s             = 1200,   /* 20 min, matching ALERT_COOLDOWN  */
        .link_down_grace_s      = 300,
    };
}

void gwrules_init(gwrules_t *g, const gwrules_cfg_t *cfg)
{
    memset(g, 0, sizeof(*g));
    g->cfg = cfg ? *cfg : gwrules_default_cfg();
}

void gwrules_note_uplink_ok(gwrules_t *g, uint32_t now_epoch)
{
    g->uplink_ok_epoch = now_epoch;
}

bool gwrules_link_is_down(const gwrules_t *g, uint32_t now_epoch)
{
    /* Nothing has ever reached the backend: on a gateway that has just booted
     * next to a dead router, that is the definition of the link being down. */
    if (g->uplink_ok_epoch == 0) return true;
    if (now_epoch < g->uplink_ok_epoch) return false;   /* clock stepped back */
    return (now_epoch - g->uplink_ok_epoch) >= g->cfg.link_down_grace_s;
}

const char *gwrules_event_name(uint8_t code)
{
    switch (code) {
    case EVT_TILT_RATE:     return "TILT RATE";
    case EVT_TILT_ABSOLUTE: return "TILT";
    case EVT_TILT_ACCEL:    return "TILT ACCELERATING";
    case EVT_VIBRATION:     return "VIBRATION";
    case EVT_DISPLACEMENT:  return "NODE MOVED";
    case EVT_NODE_TAMPER:   return "NODE DISTURBED";
    case EVT_LOW_BATTERY:   return "LOW BATTERY";
    default:                return "EVENT";
    }
}

const char *gwrules_severity_name(uint8_t severity)
{
    switch (severity) {
    case 0:  return "INFO";
    case 1:  return "WARNING";
    case 2:  return "HIGH";
    default: return "CRITICAL";
    }
}

/* Units per event code, so the message reads as a measurement rather than a
 * raw integer. An operator reading this at 3 a.m. needs to know what moved and
 * by how much, in the units they already think in. */
static const char *unit_for(uint8_t code)
{
    switch (code) {
    case EVT_TILT_RATE:     return "mdeg/h";
    case EVT_TILT_ABSOLUTE:
    case EVT_NODE_TAMPER:   return "mdeg";
    case EVT_TILT_ACCEL:    return "% of prior rate";
    case EVT_VIBRATION:     return "mg";
    case EVT_DISPLACEMENT:  return "mm";
    case EVT_LOW_BATTERY:   return "mV";
    default:                return "";
    }
}

void gwrules_compose(char *sms, size_t cap, uint16_t src, uint8_t severity,
                     uint8_t event_code, int32_t value, int32_t threshold)
{
    /* Fixed shape, most important first: what happened, where, how far past the
     * limit, and that no server was involved in deciding it. The last part is
     * not decoration -- it tells the recipient the dashboard may be showing
     * nothing at all. */
    snprintf(sms, cap, "MINEGUARD %s: %s at node 0x%04X. %ld %s (limit %ld). "
                       "Sent by the field gateway.",
             gwrules_severity_name(severity), gwrules_event_name(event_code),
             src, (long)value, unit_for(event_code), (long)threshold);
}

/* Integer square root: the tilt magnitude, without dragging libm into a module
 * that is otherwise pure integer arithmetic. */
static uint32_t isqrt64(uint64_t v)
{
    uint64_t r = 0, bit = 1ULL << 62;
    while (bit > v) bit >>= 2;
    while (bit) {
        if (v >= r + bit) { v -= r + bit; r = (r >> 1) + bit; }
        else r >>= 1;
        bit >>= 2;
    }
    return (uint32_t)r;
}

static gwrules_node_t *slot_for(gwrules_t *g, uint16_t addr)
{
    gwrules_node_t *free_slot = NULL, *oldest = &g->nodes[0];
    for (int i = 0; i < GWRULES_MAX_NODES; i++) {
        gwrules_node_t *n = &g->nodes[i];
        if (n->addr == addr) return n;
        if (n->addr == ADDR_UNASSIGNED && !free_slot) free_slot = n;
        if (n->last_sms_epoch < oldest->last_sms_epoch) oldest = n;
    }
    /* More nodes than slots: evict the one that has been quiet longest. Its
     * cooldown is the thing being lost, and a node that has not alerted in
     * hours is not the one at risk of being texted about twice. */
    gwrules_node_t *n = free_slot ? free_slot : oldest;
    memset(n, 0, sizeof(*n));
    n->addr = addr;
    return n;
}

static bool allow(gwrules_t *g, gwrules_node_t *n, uint32_t now, uint8_t severity)
{
    if (severity < g->cfg.min_severity) { g->suppressed++; return false; }
    if (n->last_sms_epoch != 0 && now >= n->last_sms_epoch &&
        (now - n->last_sms_epoch) < g->cfg.cooldown_s &&
        severity <= n->last_sev) {
        /* Inside the cooldown and no worse than last time. An escalation still
         * gets through: "it got worse" is the message people act on. */
        g->suppressed++;
        return false;
    }
    n->last_sms_epoch = now;
    n->last_sev = severity;
    g->sent++;
    return true;
}

bool gwrules_on_event(gwrules_t *g, uint16_t src, const evt_t *e,
                      uint32_t now_epoch, char *sms, size_t cap)
{
    if (!e || !sms || cap == 0) return false;

    gwrules_node_t *n = slot_for(g, src);
    if (!allow(g, n, now_epoch, e->severity)) return false;

    gwrules_compose(sms, cap, src, e->severity, e->event_code,
                    e->value, e->threshold);
    return true;
}

bool gwrules_on_telemetry(gwrules_t *g, uint16_t src, const tlm_t *t,
                          uint32_t now_epoch, char *sms, size_t cap)
{
    if (!t || !sms || cap == 0) return false;
    /* While the backend is reachable it owns this judgement: it has the node's
     * commissioning baseline, the thermal correction and the rest of the array,
     * and the gateway has none of the three. */
    if (!gwrules_link_is_down(g, now_epoch)) return false;

    gwrules_node_t *n = slot_for(g, src);

    /*
     * Raw tilt, uncorrected. Worth saying plainly: with no baseline the gateway
     * cannot tell a post that was hammered in at an angle from ground that has
     * moved, so this threshold is deliberately a blunt one -- it exists to
     * catch the case where the ground has moved so far that the distinction has
     * stopped mattering.
     */
    int64_t pitch = t->pitch_mdeg, roll = t->roll_mdeg;
    int32_t limit = (int32_t)g->cfg.tilt_alert_mdeg;
    uint32_t mag  = isqrt64((uint64_t)(pitch * pitch + roll * roll));
    uint16_t tilt_mdeg = (uint16_t)(mag > 65535 ? 65535 : mag);

    bool fired = false;
    uint8_t severity = 0;
    int32_t value = 0, threshold = 0;
    uint8_t code = 0;

    /* A local rate, from consecutive frames of this node while the link is
     * down. Two points and no fit -- cruder than the node's own estimate, which
     * is why it only decides anything when nothing better is available. */
    if (n->last_tilt_epoch && now_epoch > n->last_tilt_epoch &&
        g->cfg.tilt_rate_alert_mdeg_h > 0) {
        uint32_t dt = now_epoch - n->last_tilt_epoch;
        if (dt >= 60) {
            int32_t rate = (int32_t)(((int64_t)tilt_mdeg - n->last_tilt_mdeg)
                                     * 3600 / (int64_t)dt);
            if (rate >= (int32_t)g->cfg.tilt_rate_alert_mdeg_h) {
                fired = true; code = EVT_TILT_RATE; severity = 2;
                value = rate; threshold = g->cfg.tilt_rate_alert_mdeg_h;
            }
        }
    }
    if (!fired && limit > 0 && tilt_mdeg >= limit) {
        fired = true; code = EVT_TILT_ABSOLUTE; severity = 2;
        value = tilt_mdeg; threshold = limit;
    }

    n->last_tilt_mdeg  = tilt_mdeg;
    n->last_tilt_epoch = now_epoch;

    if (!fired) return false;
    if (!allow(g, n, now_epoch, severity)) return false;

    gwrules_compose(sms, cap, src, severity, code, value, threshold);
    return true;
}
