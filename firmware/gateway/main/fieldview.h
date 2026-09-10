/*
 * What the gateway has heard from the field, kept in RAM for the on-site UI.
 *
 * This is not a second copy of the database and must not become one. The
 * backend owns history, baselines, the reconstructed field and every judgement
 * derived from them. What lives here is the last frame from each node and a few
 * counters -- exactly what somebody standing next to the gateway with a phone
 * needs in order to answer "is the field alive, and which node is not?".
 *
 * The distinction matters. Tilt shown here is RAW: no commissioning baseline,
 * no thermal correction, so it mostly describes how each post was hammered in.
 * It is the right number for "this node is reporting" and the wrong number for
 * "this node is in trouble", and the UI labels it as such.
 */
#ifndef FIELDVIEW_H
#define FIELDVIEW_H

#include <stdbool.h>
#include <stdint.h>

#include "mesh_proto.h"

#define FIELDVIEW_MAX_NODES 32

typedef struct {
    uint16_t addr;
    uint32_t last_ms;        /* milliseconds since boot, when last heard    */
    uint32_t frames;
    int8_t   rssi;           /* as this gateway heard it                    */
    uint8_t  snr;            /* frame units: (dB + 20) * 4                  */
    uint8_t  hops;           /* path length the frame actually took         */

    bool     have_tlm;
    uint32_t tlm_epoch;
    int16_t  pitch_mdeg, roll_mdeg;
    uint16_t vib_rms_mg;
    int16_t  temp_c_x100;
    uint16_t vbat_mv;
    uint8_t  gnss_status;
    uint8_t  flags;

    uint8_t  last_evt_code, last_evt_sev;
    uint32_t last_evt_epoch;
} fieldview_node_t;

void fieldview_init(void);

/* Any frame from this node, whatever its type. */
void fieldview_heard(uint16_t addr, int8_t rssi, uint8_t snr, uint8_t hops,
                     uint32_t now_ms);
void fieldview_telemetry(uint16_t addr, const tlm_t *t);
void fieldview_event(uint16_t addr, const evt_t *e);

int  fieldview_count(void);

/* Copy out one entry. Returns false past the end. Copying rather than handing
 * back a pointer keeps the lock inside this module: the table is written by the
 * radio task and read by the web server. */
bool fieldview_get(int index, fieldview_node_t *out);

#endif /* FIELDVIEW_H */
