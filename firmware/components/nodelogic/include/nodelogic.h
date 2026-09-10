/*
 * The node's judgement, with no hardware in it.
 *
 * Everything a node decides for itself lives here: what its tilt is once the
 * calibration offsets are applied, how fast that tilt is moving, whether any of
 * that crosses a threshold hard enough to be worth waking the network for, and
 * whether it has said so recently enough that saying it again would be noise.
 *
 * It is a separate, ESP-IDF-free module for the same reason the frame codec is:
 * these are the decisions that determine whether the system warns anybody, and
 * they should be testable with cc on a laptop rather than by planting a node and
 * waiting for a hillside to move. host_test/ drives every branch below.
 *
 * The rate threshold is the one that matters. There is no crack gauge in this
 * design, so a first crack opening is not directly observable -- what is
 * observable is that tilt starts moving faster, and it does that while absolute
 * tilt is still comfortably inside its own limit. A node that only checked
 * absolute tilt would be a logger that reports a collapse after it happens.
 */
#ifndef NODELOGIC_H
#define NODELOGIC_H

#include <stdbool.h>
#include <stdint.h>

#include "mesh_proto.h"

/* Tilt history retained across deep sleep. Sixteen points at the default 60 s
 * cadence is sixteen minutes -- enough to fit a rate through, small enough to
 * sit in the 8 KB of RTC memory that survives sleep alongside everything else.
 * At a slower configured interval it simply spans proportionally longer. */
#define NODELOGIC_HIST          16

/* Nothing useful can be said about a rate from two points a few seconds apart:
 * the LIS3DH's own noise would dominate the slope entirely. */
#define NODELOGIC_MIN_SPAN_S    300
#define NODELOGIC_MIN_POINTS    3
#define NODELOGIC_RATE_WINDOW_S 3600

/* Per event code. A node that repeats itself every cycle gets muted by the
 * people it is meant to warn, and a muted node is worse than no node -- but an
 * event that escalates in severity is new information and bypasses this. */
#define NODELOGIC_COOLDOWN_S    600

/* A tilt step no ground movement can produce in one cycle: the post has been
 * pulled, knocked by plant, or stolen. */
#define NODELOGIC_TAMPER_MDEG   5000

/* Matches GNSS_DISPLACEMENT_ALARM_M in backend/app/ingest.py. A node that has
 * moved this far has not subsided; it has been carried. */
#define NODELOGIC_DISPLACE_M    15.0f

/* Li-ion, loaded. Below the first figure the node warns; below the second it is
 * within a few hours of the protection circuit cutting it off. */
#define NODELOGIC_VBAT_LOW_MV      3400
#define NODELOGIC_VBAT_CRIT_MV     3200
#define NODELOGIC_VBAT_RECOVER_MV  3550   /* hysteresis: solar recovers by day */

#define NODELOGIC_MAX_EVENTS    4

typedef struct {
    uint32_t t_epoch;
    uint16_t tilt_mdeg;      /* magnitude from the configured zero */
} nodelogic_point_t;

/*
 * Retained in RTC memory across deep sleep -- which is the only reason a node
 * that is awake for two seconds a minute can speak about rates at all. Losing
 * this on every wake would leave the node with a single reading and no history,
 * and the rate trigger would never fire.
 */
typedef struct {
    uint32_t magic;
    nodelogic_point_t hist[NODELOGIC_HIST];
    uint8_t  head;                  /* next write position          */
    uint8_t  count;
    uint32_t last_evt_epoch[8];     /* indexed by EVT_* code        */
    uint8_t  last_evt_sev[8];
    bool     low_battery;           /* latched, released by hysteresis */
    bool     home_valid;
    int32_t  home_lat_e7, home_lon_e7;
} nodelogic_t;

typedef struct {
    uint32_t t_epoch;
    bool     time_valid;        /* false until a TIME_SYNC or a GNSS fix arrives */
    int16_t  pitch_mdeg;        /* raw, before the calibration offsets  */
    int16_t  roll_mdeg;
    bool     tilt_valid;
    uint16_t vib_rms_mg;
    bool     vib_valid;
    uint16_t vbat_mv;
    bool     woke_on_impact;    /* EXT1 fired: accelerometer or vibration switch */
    bool     fix_valid;
    int32_t  lat_e7, lon_e7;
} nodelogic_input_t;

typedef struct {
    uint16_t tilt_mdeg;         /* magnitude after offsets                  */
    int32_t  tilt_rate_mdeg_h;  /* signed: tilt can recover as well as grow */
    bool     rate_valid;        /* false when the history is too short      */
    uint8_t  flags;             /* TLM_FLAG_* to OR into the telemetry frame */
    uint8_t  n_events;
    evt_t    events[NODELOGIC_MAX_EVENTS];
} nodelogic_out_t;

/* Clear the retained state. Called when RTC memory does not carry the magic --
 * a cold boot, a firmware change, or a brownout. */
void nodelogic_reset(nodelogic_t *s);

/* True when the retained state looks like ours rather than whatever the last
 * firmware left in RTC memory. */
bool nodelogic_valid(const nodelogic_t *s);

/* Where the node was commissioned. Displacement is measured against this, so it
 * is set once from the first good fix and then left alone -- re-homing on every
 * fix would let a node drift away from its post one metre at a time and never
 * notice. */
void nodelogic_set_home(nodelogic_t *s, int32_t lat_e7, int32_t lon_e7);

/*
 * One cycle's worth of thinking: apply the offsets, update the history, work
 * out the rate, and emit whatever events the thresholds imply.
 *
 * `out->events` are complete evt_t payloads, ready to be framed and sent
 * immediately -- an EVENT bypasses the duty cycle, which is what makes this an
 * early-warning system rather than a logger.
 */
void nodelogic_evaluate(nodelogic_t *s, const nodelogic_input_t *in,
                        const cfg_t *cfg, nodelogic_out_t *out);

/* Tilt rate in milli-degrees per hour over `window_s`, and whether enough
 * history existed to mean anything. Exposed for the tests and for the CLI. */
bool nodelogic_tilt_rate(const nodelogic_t *s, uint32_t now_epoch,
                         uint32_t window_s, int32_t *rate_mdeg_h);

/* Severity from how far past its threshold a value has gone: 1 warning,
 * 2 high, 3 critical. A breach at 1.01x and a breach at 10x are not the same
 * event and should not wake the same number of people. */
uint8_t nodelogic_severity(int32_t value, int32_t threshold);

/* Coarse state of charge for a single Li-ion cell under load. Coarse on
 * purpose: the discharge curve is flat across the middle and any finer figure
 * would be invented. */
uint8_t nodelogic_battery_pct(uint16_t mv);

#endif /* NODELOGIC_H */
