/*
 * NMEA parsing and geodesy -- the parts with no hardware in them.
 *
 * Split out so the host tests can drive the parser with real captured
 * sentences, including the malformed ones a receiver emits for minutes while it
 * is still acquiring. That is exactly when a naive parser reports a confident
 * position off the coast of Africa, and exactly the bug you do not want to find
 * after planting twenty-one nodes.
 */
#ifndef GNSS_NMEA_H
#define GNSS_NMEA_H

#include <stdbool.h>
#include <stdint.h>

#include "mesh_proto.h"   /* GNSS_NO_FIX / GNSS_FIX_2D / GNSS_FIX_3D / _DGPS */

typedef struct {
    bool     valid;
    uint8_t  fix;        /* GNSS_* fix quality                               */
    uint8_t  sats;
    int32_t  lat_e7;
    int32_t  lon_e7;
    int16_t  alt_m;
    uint16_t h_acc_cm;   /* derived from HDOP; an estimate, and named as one */
    uint32_t t_epoch;    /* 0 when no sentence carried a usable date         */
} gnss_fix_t;

/* Parse one sentence into `fix`. Returns true if it recognised the sentence. */
bool gnss_parse_nmea(const char *line, gnss_fix_t *fix);

/* Great-circle distance in metres, for deciding whether a node has moved. */
float gnss_distance_m(int32_t lat1_e7, int32_t lon1_e7,
                      int32_t lat2_e7, int32_t lon2_e7);

#endif /* GNSS_NMEA_H */
