#include <math.h>
#include <string.h>

#include "gnss_nmea.h"     /* gnss_distance_m -- pure geodesy, no hardware */
#include "nodelogic.h"

#define NODELOGIC_MAGIC 0x4E4C4731u   /* "NLG1" */

void nodelogic_reset(nodelogic_t *s)
{
    memset(s, 0, sizeof(*s));
    s->magic = NODELOGIC_MAGIC;
}

bool nodelogic_valid(const nodelogic_t *s)
{
    return s->magic == NODELOGIC_MAGIC && s->count <= NODELOGIC_HIST
        && s->head < NODELOGIC_HIST;
}

void nodelogic_set_home(nodelogic_t *s, int32_t lat_e7, int32_t lon_e7)
{
    s->home_lat_e7 = lat_e7;
    s->home_lon_e7 = lon_e7;
    s->home_valid  = true;
}

uint8_t nodelogic_severity(int32_t value, int32_t threshold)
{
    if (threshold <= 0) return 1;
    int64_t v = value < 0 ? -(int64_t)value : (int64_t)value;
    if (v >= (int64_t)threshold * 3) return 3;
    if (v >= (int64_t)threshold * 3 / 2) return 2;
    return 1;
}

uint8_t nodelogic_battery_pct(uint16_t mv)
{
    /* Five straight segments through the loaded discharge curve of a single
     * 18650. The middle of that curve is nearly flat, so a percentage derived
     * from voltage there is worth about +/-20% -- which is why the alerting
     * thresholds above are in millivolts and this figure is only ever
     * displayed. */
    static const struct { uint16_t mv; uint8_t pct; } curve[] = {
        { 3000,   0 }, { 3300,  10 }, { 3600,  40 },
        { 3900,  75 }, { 4100,  95 }, { 4200, 100 },
    };
    const int n = (int)(sizeof(curve) / sizeof(curve[0]));
    if (mv <= curve[0].mv)     return 0;
    if (mv >= curve[n-1].mv)   return 100;
    for (int i = 1; i < n; i++) {
        if (mv <= curve[i].mv) {
            uint16_t span = (uint16_t)(curve[i].mv - curve[i-1].mv);
            uint8_t  rise = (uint8_t)(curve[i].pct - curve[i-1].pct);
            return (uint8_t)(curve[i-1].pct + (mv - curve[i-1].mv) * rise / span);
        }
    }
    return 100;
}

/* ------------------------------------------------------------------ history */

static void hist_push(nodelogic_t *s, uint32_t t_epoch, uint16_t tilt_mdeg)
{
    s->hist[s->head] = (nodelogic_point_t){ .t_epoch = t_epoch, .tilt_mdeg = tilt_mdeg };
    s->head = (uint8_t)((s->head + 1) % NODELOGIC_HIST);
    if (s->count < NODELOGIC_HIST) s->count++;
}

/* Most recent point first. */
static const nodelogic_point_t *hist_at(const nodelogic_t *s, uint8_t back)
{
    if (back >= s->count) return NULL;
    int idx = (int)s->head - 1 - (int)back;
    while (idx < 0) idx += NODELOGIC_HIST;
    return &s->hist[idx];
}

/*
 * Least squares over the points inside the window, not the difference between
 * the first and the last. With ~50 mdeg of noise on each reading, a two-point
 * slope over ten minutes carries about 600 mdeg/h of noise -- four times the
 * default threshold, which would make the primary early-warning trigger fire on
 * nothing at all. Fitting all the points divides that by roughly sqrt(n).
 */
bool nodelogic_tilt_rate(const nodelogic_t *s, uint32_t now_epoch,
                         uint32_t window_s, int32_t *rate_mdeg_h)
{
    *rate_mdeg_h = 0;

    double sx = 0, sy = 0, sxx = 0, sxy = 0;
    uint32_t n = 0, t_oldest = 0, t_newest = 0;

    for (uint8_t i = 0; i < s->count; i++) {
        const nodelogic_point_t *p = hist_at(s, i);
        if (p->t_epoch == 0) continue;
        if (p->t_epoch > now_epoch) continue;             /* clock stepped back */
        if (now_epoch - p->t_epoch > window_s) continue;

        double x = (double)p->t_epoch;                    /* seconds */
        double y = (double)p->tilt_mdeg;
        sx += x; sy += y; sxx += x * x; sxy += x * y;
        if (n == 0 || p->t_epoch < t_oldest) t_oldest = p->t_epoch;
        if (p->t_epoch > t_newest) t_newest = p->t_epoch;
        n++;
    }

    if (n < NODELOGIC_MIN_POINTS) return false;
    if (t_newest - t_oldest < NODELOGIC_MIN_SPAN_S) return false;

    double denom = (double)n * sxx - sx * sx;
    if (denom <= 0.0) return false;                       /* all one timestamp */

    double slope_per_s = ((double)n * sxy - sx * sy) / denom;
    double per_hour = slope_per_s * 3600.0;
    if (per_hour >  2147483000.0) per_hour =  2147483000.0;
    if (per_hour < -2147483000.0) per_hour = -2147483000.0;
    *rate_mdeg_h = (int32_t)per_hour;
    return true;
}

/* Recent rate against the rate before it. Tilt that is merely large is a node
 * on a slope; tilt that is accelerating is ground giving way, and it shows up
 * here before either absolute limit is reached. */
static bool tilt_is_accelerating(const nodelogic_t *s, uint32_t now_epoch,
                                 int32_t recent_rate, int32_t *ratio_x100)
{
    *ratio_x100 = 0;
    if (s->count < NODELOGIC_HIST / 2) return false;

    /* The older half of the window, taken as its own fit. */
    nodelogic_t older = *s;
    older.count = (uint8_t)(s->count / 2);
    older.head  = (uint8_t)(((int)s->head - (int)(s->count / 2) + NODELOGIC_HIST * 2)
                            % NODELOGIC_HIST);

    int32_t before = 0;
    const nodelogic_point_t *mid = hist_at(&older, 0);
    if (!mid) return false;
    if (!nodelogic_tilt_rate(&older, mid->t_epoch, NODELOGIC_RATE_WINDOW_S, &before))
        return false;

    (void)now_epoch;
    if (recent_rate <= 0) return false;
    if (before <= 0) return recent_rate > 0;    /* was flat or recovering, now rising */

    *ratio_x100 = (int32_t)((int64_t)recent_rate * 100 / before);
    return *ratio_x100 >= 200;                   /* twice as fast as it was */
}

/* ------------------------------------------------------------------- events */

static bool cooldown_passed(const nodelogic_t *s, uint8_t code, uint32_t now,
                            uint8_t severity)
{
    if (code >= 8) return true;
    uint32_t last = s->last_evt_epoch[code];
    if (last == 0) return true;
    if (severity > s->last_evt_sev[code]) return true;    /* escalation is news */
    if (now < last) return true;                          /* clock stepped back */
    return (now - last) >= NODELOGIC_COOLDOWN_S;
}

static void emit(nodelogic_t *s, nodelogic_out_t *out, uint32_t now,
                 uint8_t code, uint8_t severity, int32_t value, int32_t threshold)
{
    if (out->n_events >= NODELOGIC_MAX_EVENTS) return;
    if (!cooldown_passed(s, code, now, severity)) return;

    out->events[out->n_events++] = (evt_t){
        .t_epoch = now, .event_code = code, .severity = severity,
        .value = value, .threshold = threshold,
    };
    if (code < 8) {
        s->last_evt_epoch[code] = now;
        s->last_evt_sev[code]   = severity;
    }
}

static uint16_t tilt_magnitude(int32_t pitch, int32_t roll)
{
    /* The magnitude of the tilt vector, not the larger of the two axes: a post
     * leaning equally in both directions is tilted by 1.41x either component,
     * and calling that the smaller number would under-report every diagonal
     * movement in the field. */
    double m = sqrt((double)pitch * pitch + (double)roll * roll);
    return (uint16_t)(m > 65535.0 ? 65535.0 : m);
}

void nodelogic_evaluate(nodelogic_t *s, const nodelogic_input_t *in,
                        const cfg_t *cfg, nodelogic_out_t *out)
{
    memset(out, 0, sizeof(*out));
    if (!nodelogic_valid(s)) nodelogic_reset(s);

    /* -- tilt, against the calibration zero ------------------------------- */
    int32_t pitch = (int32_t)in->pitch_mdeg - cfg->tilt_offset_pitch;
    int32_t roll  = (int32_t)in->roll_mdeg  - cfg->tilt_offset_roll;
    out->tilt_mdeg = in->tilt_valid ? tilt_magnitude(pitch, roll) : 0;

    if (!in->tilt_valid) out->flags |= TLM_FLAG_TILT_FAULT;
    if (!in->vib_valid)  out->flags |= TLM_FLAG_VIB_FAULT;
    if (!in->fix_valid)  out->flags |= TLM_FLAG_GNSS_FAULT;
    if (cfg->tilt_offset_pitch == 0 && cfg->tilt_offset_roll == 0)
        out->flags |= TLM_FLAG_UNCALIBRATED;

    /* -- battery, with hysteresis ----------------------------------------- */
    if (in->vbat_mv > 0) {
        if (!s->low_battery && in->vbat_mv <= NODELOGIC_VBAT_LOW_MV)
            s->low_battery = true;
        else if (s->low_battery && in->vbat_mv >= NODELOGIC_VBAT_RECOVER_MV)
            s->low_battery = false;   /* a solar node crosses this every morning */
    }
    if (s->low_battery) out->flags |= TLM_FLAG_LOW_BATTERY;

    /*
     * Without a disciplined clock the node still measures, still transmits and
     * still reports faults -- but every remaining judgement here is about rates
     * and cooldowns, and both are meaningless against timestamps that do not
     * advance. It reports and waits for a TIME_SYNC rather than inventing a
     * rate from a free-running counter.
     */
    if (!in->time_valid) return;

    /* -- history and rate -------------------------------------------------- */
    uint16_t previous = 0;
    bool had_previous = false;
    const nodelogic_point_t *last = hist_at(s, 0);
    if (last && last->t_epoch) { previous = last->tilt_mdeg; had_previous = true; }

    if (in->tilt_valid) hist_push(s, in->t_epoch, out->tilt_mdeg);

    if (nodelogic_tilt_rate(s, in->t_epoch, NODELOGIC_RATE_WINDOW_S,
                            &out->tilt_rate_mdeg_h))
        out->rate_valid = true;

    /* -- the thresholds, most informative first ---------------------------- */

    /* Rate. The precursor: it crosses while absolute tilt is still fine. */
    if (out->rate_valid && cfg->tilt_rate_alert_mdeg_h > 0 &&
        out->tilt_rate_mdeg_h >= (int32_t)cfg->tilt_rate_alert_mdeg_h) {
        emit(s, out, in->t_epoch, EVT_TILT_RATE,
             nodelogic_severity(out->tilt_rate_mdeg_h, cfg->tilt_rate_alert_mdeg_h),
             out->tilt_rate_mdeg_h, cfg->tilt_rate_alert_mdeg_h);
    }

    /* Acceleration. Reported even below the rate limit, because the shape of
     * the curve is the warning -- doubling from a small number is what the hour
     * before a collapse looks like. */
    int32_t ratio_x100 = 0;
    if (out->rate_valid &&
        tilt_is_accelerating(s, in->t_epoch, out->tilt_rate_mdeg_h, &ratio_x100)) {
        emit(s, out, in->t_epoch, EVT_TILT_ACCEL,
             ratio_x100 >= 400 ? 3 : 2, ratio_x100, 200);
    }

    /* Absolute tilt. */
    if (in->tilt_valid && cfg->tilt_alert_mdeg > 0 &&
        out->tilt_mdeg >= cfg->tilt_alert_mdeg) {
        emit(s, out, in->t_epoch, EVT_TILT_ABSOLUTE,
             nodelogic_severity(out->tilt_mdeg, cfg->tilt_alert_mdeg),
             out->tilt_mdeg, cfg->tilt_alert_mdeg);
    }

    /* A step this large in one cycle is not the ground. Someone has moved the
     * post -- and a node reporting the movement of its own installation as
     * subsidence would poison the whole array's reconstruction. */
    if (in->tilt_valid && had_previous) {
        int32_t jump = (int32_t)out->tilt_mdeg - (int32_t)previous;
        if (jump < 0) jump = -jump;
        if (jump >= NODELOGIC_TAMPER_MDEG)
            emit(s, out, in->t_epoch, EVT_NODE_TAMPER, 2, jump, NODELOGIC_TAMPER_MDEG);
    }

    /* Vibration. Only when the sensor is enabled: a node with the flag off is
     * one whose vibration channel has been switched off deliberately, and
     * alerting from it anyway would make that switch a lie. */
    if (in->vib_valid && (cfg->flags & CFG_FLAG_VIB_ENABLED) &&
        cfg->vib_alert_mg > 0 && in->vib_rms_mg >= cfg->vib_alert_mg) {
        emit(s, out, in->t_epoch, EVT_VIBRATION,
             nodelogic_severity(in->vib_rms_mg, cfg->vib_alert_mg),
             in->vib_rms_mg, cfg->vib_alert_mg);
    } else if (in->woke_on_impact && in->vib_valid) {
        /* Woken by the switch or the accelerometer, but the averaged RMS has
         * already died away -- a blast, or plant driving past. Worth one
         * low-severity report so the record shows what disturbed the node,
         * not worth waking anybody. */
        emit(s, out, in->t_epoch, EVT_VIBRATION, 1, in->vib_rms_mg,
             cfg->vib_alert_mg);
    }

    /* Displacement: metres, which is the one thing a NEO-6M can honestly
     * resolve. Subsidence is millimetres and this will never see it. */
    if (in->fix_valid && (cfg->flags & CFG_FLAG_GNSS_ENABLED)) {
        if (!s->home_valid) {
            nodelogic_set_home(s, in->lat_e7, in->lon_e7);
        } else {
            float moved = gnss_distance_m(s->home_lat_e7, s->home_lon_e7,
                                          in->lat_e7, in->lon_e7);
            if (moved >= NODELOGIC_DISPLACE_M)
                emit(s, out, in->t_epoch, EVT_DISPLACEMENT, 3,
                     (int32_t)(moved * 1000.0f),
                     (int32_t)(NODELOGIC_DISPLACE_M * 1000.0f));
        }
    }

    /* Battery. Last, because it is the least urgent and the event buffer is
     * small -- if four things are wrong at once, the ground matters more than
     * the cell. */
    if (in->vbat_mv > 0 && s->low_battery) {
        emit(s, out, in->t_epoch, EVT_LOW_BATTERY,
             in->vbat_mv <= NODELOGIC_VBAT_CRIT_MV ? 2 : 1,
             in->vbat_mv, NODELOGIC_VBAT_LOW_MV);
    }
}
