/*
 * What the gateway's one LED is allowed to say, and how it says it.
 *
 * A single LED on a box in the rain is a genuinely constrained display, and the
 * temptation is to make it mean "powered", which is a fact nobody needed. This
 * one answers the question somebody actually walks over to ask: *is this thing
 * working, and if not, which part is broken?* -- from ten metres away, at night,
 * without a laptop.
 *
 * It reports the WORST thing that is true, not a summary. A gateway with a dead
 * radio and a fine backhaul is a dead gateway, and averaging the two into
 * "mostly OK" would be a lie told in the field, where lies are expensive.
 *
 * The board's onboard NeoPixel gives two channels to say it in, and both are
 * used deliberately:
 *
 *   COLOUR says how bad it is.   red = this gateway is not doing its job
 *                                amber = degraded, but no data is being lost
 *                                green = working
 *                                blue = a frame just arrived
 *
 *   BLINK COUNT says which fault it is, read the way a car's diagnostic flash
 *   is read: N short blinks, then a pause, repeating.
 *
 * Colour alone would not do. Six distinguishable hues do not survive a dirty
 * enclosure, low battery brightness, or the roughly one man in twelve who
 * cannot separate red from green -- so the colour is the summary and the count
 * is the fact. Either one alone is still useful; together they are unambiguous.
 *
 * Pure logic, no ESP-IDF: the mapping from state to meaning is the part worth
 * testing, and host_test/ does.
 */
#ifndef STATUSLED_PATTERN_H
#define STATUSLED_PATTERN_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Ordered worst-first: statusled_evaluate() returns the first one that is
 * true, so the enum order IS the priority. */
typedef enum {
    LED_RADIO_DOWN = 0,   /* the radio never came up: nothing can arrive     */
    LED_FIELD_SILENT,     /* radio fine, but no node has been heard in a while */
    LED_NO_MODEM,         /* the offline alerting path is gone               */
    LED_NO_WIFI,          /* no site network at all                          */
    LED_BACKEND_DOWN,     /* WiFi up, backend unreachable -- spooling        */
    LED_SPOOL_FILLING,    /* the backlog is deep enough to start shedding    */
    LED_OK,
    LED_CODE_COUNT,
} statusled_code_t;

typedef struct {
    bool     radio_up;
    bool     wifi_up;
    bool     backend_ok;
    bool     modem_ready;
    bool     modem_registered;
    uint32_t spool_depth;
    /* Since the last frame from any node. UINT32_MAX before the first one. */
    uint32_t quiet_s;
    /* Grace period after boot, during which "no node heard yet" is normal
     * rather than a fault -- the field wakes on a 60 s duty cycle. */
    uint32_t uptime_s;
} statusled_input_t;

/* The field is expected to be quiet between duty cycles; three minutes of
 * silence from every node at once is not a duty cycle, it is a fault. Matches
 * the backend's node_stale_seconds so the LED and the dashboard cannot
 * disagree about which node has gone away. */
#define STATUSLED_QUIET_S       180

/* Below this the spool is doing its job; above it, the backlog is deep enough
 * that the oldest frames are in danger. */
#define STATUSLED_SPOOL_DEEP    500

/* Nothing is wrong with a gateway that has been up for ten seconds and heard
 * nobody yet. */
#define STATUSLED_SETTLE_S      120

/* A colour, at the low brightness this thing is driven at. */
typedef struct {
    uint8_t r, g, b;
} statusled_rgb_t;

statusled_code_t statusled_evaluate(const statusled_input_t *in);

/*
 * The colour for a code, and the one for a received frame.
 *
 * Values are small on purpose. A WS2812 at full scale is genuinely painful to
 * look at, useless for reading a blink count, and on a solar gateway it is
 * current spent on being annoying.
 */
statusled_rgb_t statusled_colour(statusled_code_t code);
statusled_rgb_t statusled_frame_colour(void);

/* "#22c55e", for the web UI -- so the chip on the page is the colour of the
 * light on the box. */
void statusled_colour_hex(statusled_code_t code, char *out, size_t cap);

/* Blinks per cycle. LED_RADIO_DOWN is the exception: it is not counted, it is
 * a continuous fast flash, because a gateway that cannot hear its field should
 * look wrong from across the yard rather than needing to be counted. */
uint8_t statusled_blinks(statusled_code_t code);

/* A short machine-readable tag ("backend_down") and a sentence for a human.
 * Both appear in the gateway's JSON, so the web UI can tell somebody what the
 * thing they are looking at means. */
const char *statusled_tag(statusled_code_t code);
const char *statusled_meaning(statusled_code_t code);

#endif /* STATUSLED_PATTERN_H */
