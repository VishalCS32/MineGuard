/*
 * NMEA parsing and geodesy. No ESP-IDF, so the host tests can drive it with
 * real captured sentences -- including the malformed ones a receiver emits
 * while it is still acquiring, which is when a naive parser produces a
 * confident position in the Gulf of Guinea.
 */
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "gnss_nmea.h"

/* M_PI is not in ISO C; glibc hides it under a strict -std=c11 and the
 * cross-toolchain's newlib does not always supply it either. Defining it here
 * keeps this file compiling identically on the host and on the target. */
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* Split on commas in place is destructive; NMEA fields are read by index
 * instead so the caller's buffer is never modified. */
static bool field(const char *line, int index, char *out, size_t cap)
{
    int idx = 0;
    const char *p = line;
    while (idx < index) {
        p = strchr(p, ',');
        if (!p) return false;
        p++;
        idx++;
    }
    const char *end = strchr(p, ',');
    size_t n = end ? (size_t)(end - p) : strlen(p);
    /* Trim a trailing checksum on the last field. */
    const char *star = memchr(p, '*', n);
    if (star) n = (size_t)(star - p);
    if (n >= cap) n = cap - 1;
    memcpy(out, p, n);
    out[n] = '\0';
    return true;
}

/* NMEA gives ddmm.mmmm, which is not degrees and is the classic way to land a
 * node a few hundred kilometres from where it is. */
static int32_t dm_to_e7(const char *dm, const char *hemi)
{
    if (!dm[0]) return 0;
    double v = atof(dm);
    int deg = (int)(v / 100.0);
    double min = v - deg * 100.0;
    double dec = deg + min / 60.0;
    if (hemi[0] == 'S' || hemi[0] == 'W') dec = -dec;
    return (int32_t)llround(dec * 1e7);
}

static uint32_t nmea_epoch(const char *hhmmss, const char *ddmmyy)
{
    if (strlen(hhmmss) < 6 || strlen(ddmmyy) < 6) return 0;

    int hh = (hhmmss[0]-'0')*10 + (hhmmss[1]-'0');
    int mm = (hhmmss[2]-'0')*10 + (hhmmss[3]-'0');
    int ss = (hhmmss[4]-'0')*10 + (hhmmss[5]-'0');
    int dd = (ddmmyy[0]-'0')*10 + (ddmmyy[1]-'0');
    int mo = (ddmmyy[2]-'0')*10 + (ddmmyy[3]-'0');
    int yy = (ddmmyy[4]-'0')*10 + (ddmmyy[5]-'0');
    if (mo < 1 || mo > 12 || dd < 1 || dd > 31) return 0;

    int year = 2000 + yy;
    /* Days from the epoch, by the civil-from-days algorithm -- no libc time, no
     * timezone database, no surprises on a device with neither. */
    int y = year - (mo <= 2);
    int era = (y >= 0 ? y : y - 399) / 400;
    unsigned yoe = (unsigned)(y - era * 400);
    unsigned doy = (unsigned)((153 * (mo + (mo > 2 ? -3 : 9)) + 2) / 5 + dd - 1);
    unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    long days = (long)era * 146097 + (long)doe - 719468;

    return (uint32_t)(days * 86400L + hh * 3600 + mm * 60 + ss);
}

bool gnss_parse_nmea(const char *line, gnss_fix_t *fix)
{
    if (!line || line[0] != '$') return false;

    /* Talker ID varies with constellation (GP, GN, GL...), so match on the
     * sentence type rather than the whole prefix. */
    const char *type = line + 3;

    if (!strncmp(type, "GGA", 3)) {
        char f[16], hemi[4];
        if (!field(line, 6, f, sizeof(f))) return false;
        int quality = atoi(f);
        if (quality <= 0) {           /* still acquiring: no position at all */
            fix->fix = GNSS_NO_FIX;
            fix->valid = false;
            return true;
        }
        fix->fix = (quality >= 2) ? GNSS_FIX_DGPS : GNSS_FIX_3D;

        if (field(line, 7, f, sizeof(f))) fix->sats = (uint8_t)atoi(f);

        char lat[16], lon[16];
        if (field(line, 2, lat, sizeof(lat)) && field(line, 3, hemi, sizeof(hemi)))
            fix->lat_e7 = dm_to_e7(lat, hemi);
        if (field(line, 4, lon, sizeof(lon)) && field(line, 5, hemi, sizeof(hemi)))
            fix->lon_e7 = dm_to_e7(lon, hemi);
        if (field(line, 9, f, sizeof(f))) fix->alt_m = (int16_t)atof(f);

        /* HDOP scaled by a nominal 2.5 m UERE. An estimate, and the frame calls
         * it one -- h_acc_cm, not h_acc. */
        if (field(line, 8, f, sizeof(f))) {
            double hdop = atof(f);
            if (hdop <= 0) hdop = 99.9;
            double acc_m = hdop * 2.5;
            if (acc_m > 655.0) acc_m = 655.0;
            fix->h_acc_cm = (uint16_t)(acc_m * 100.0);
        }
        fix->valid = fix->lat_e7 != 0 || fix->lon_e7 != 0;
        return true;
    }

    if (!strncmp(type, "GSA", 3)) {
        char f[8];
        if (!field(line, 2, f, sizeof(f))) return false;
        int mode = atoi(f);           /* 1 none, 2 = 2-D, 3 = 3-D */
        if (mode == 2 && fix->fix < GNSS_FIX_2D) fix->fix = GNSS_FIX_2D;
        if (mode == 1) { fix->fix = GNSS_NO_FIX; fix->valid = false; }
        /* A 2-D fix has no usable altitude, and altitude is the axis subsidence
         * lives on. Downgrade rather than let it look like a 3-D fix. */
        if (mode == 2 && fix->fix > GNSS_FIX_2D) fix->fix = GNSS_FIX_2D;
        return true;
    }

    if (!strncmp(type, "RMC", 3)) {
        char status[4], t[16], d[16];
        if (!field(line, 2, status, sizeof(status))) return false;
        if (status[0] != 'A') return true;            /* 'V' = void */
        if (field(line, 1, t, sizeof(t)) && field(line, 9, d, sizeof(d)))
            fix->t_epoch = nmea_epoch(t, d);
        return true;
    }
    return false;
}

float gnss_distance_m(int32_t lat1_e7, int32_t lon1_e7,
                      int32_t lat2_e7, int32_t lon2_e7)
{
    const double R = 6371000.0;
    double lat1 = lat1_e7 / 1e7 * M_PI / 180.0;
    double lat2 = lat2_e7 / 1e7 * M_PI / 180.0;
    double dlat = lat2 - lat1;
    double dlon = (lon2_e7 - lon1_e7) / 1e7 * M_PI / 180.0;

    double a = sin(dlat / 2) * sin(dlat / 2) +
               cos(lat1) * cos(lat2) * sin(dlon / 2) * sin(dlon / 2);
    if (a > 1.0) a = 1.0;
    return (float)(2.0 * R * asin(sqrt(a)));
}
