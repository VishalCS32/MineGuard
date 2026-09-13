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

    /*
     * A node's codes, and a separate language spoken on a separate box. They
     * reuse the low blink counts on purpose: nobody stands in front of a node
     * and a gateway at the same time, and short counts are easier to read than
     * long ones. What a node's light answers is narrower -- "is the radio
     * working, and does it have anybody to talk to?" -- because that is the
     * only question a box on a post in a field can usefully be asked.
     */
    LED_NODE_RADIO_DOWN,  /* the LLCC68 did not answer on SPI at all         */
    LED_NODE_TX_FAILING,  /* it initialised, but transmits are not completing */
    LED_NODE_NO_MESH,     /* transmitting fine, nothing ever heard back       */
    LED_NODE_LINK_STALE,  /* heard the mesh once, nothing for a long while    */
    LED_NODE_OK,

    LED_CODE_COUNT,
} statusled_code_t;

/* The first node code, so a loop can tell the two vocabularies apart. */
#define LED_NODE_FIRST  LED_NODE_RADIO_DOWN

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

/*
 * What a node is allowed to hear, and how long it may hear nothing.
 *
 * A node is not a gateway: it is not addressed by anybody most of the time,
 * and if it is not relaying it may legitimately hear only the gateway's
 * TIME_SYNC -- which arrives every 600 s. So the threshold is one missed sync
 * plus margin, not the three minutes a gateway is held to. Any shorter and a
 * perfectly healthy non-relay node would sit there reporting a fault between
 * syncs, which would teach whoever installed it to ignore the light.
 */
#define STATUSLED_NODE_QUIET_S  660

/*
 * How long a node may have heard NOTHING AT ALL before that is a fault.
 *
 * Not the gateway's settle window, which is the mistake this constant exists
 * to correct. A gateway hears its field every 60 s, so two minutes of silence
 * is already wrong. A node is on the other side of that asymmetry: it is not
 * addressed by anybody most of the time, and the first frame it can expect to
 * hear is the gateway's TIME_SYNC -- up to 600 s away, and up to 600 s away
 * from a gateway that is working perfectly. Judging a node at 120 s reports
 * "no mesh" on a healthy link for the first eight minutes of every boot,
 * which is exactly the false alarm that gets an indicator ignored.
 */
#define STATUSLED_NODE_SETTLE_S 660

typedef struct {
    bool     radio_up;      /* llcc68_init() succeeded                       */
    /* The last transmit attempt completed. A radio that initialises and then
     * cannot send is the failure a "powered" light would hide: the SPI wiring
     * is fine, so everything looks healthy, and nothing ever leaves the box. */
    bool     tx_ok;
    /* Since the last frame heard from anyone. UINT32_MAX before the first. */
    uint32_t heard_s;
    uint32_t uptime_s;
} statusled_node_input_t;

statusled_code_t statusled_evaluate_node(const statusled_node_input_t *in);

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
