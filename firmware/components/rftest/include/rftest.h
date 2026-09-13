/*
 * The RF link test: does this radio actually move bytes to that radio?
 *
 * WHY THIS EXISTS. Every other diagnostic in the system is downstream of a
 * working link, so none of them can tell you the link is the problem. A node
 * that initialises its LLCC68 and then reports nothing looks exactly like a
 * node with a disconnected antenna, a node out of range, and a node whose
 * gateway is off -- four different jobs, one symptom. On a hillside with
 * twenty-one posts to commission before dark, guessing between them is the
 * expensive part of the day.
 *
 * So: send N numbered frames, have the far end echo each one back with the
 * signal strength IT measured, and print what came back. That yields the four
 * numbers that actually decide whether a link will hold:
 *
 *   loss %       the only honest measure of a link. A link at 30% loss still
 *                "works" if you only ever send one frame and get lucky.
 *   RTT          proves the round trip, and at LoRa airtimes an RTT well over
 *                the expected one means retries or a busy channel.
 *   RSSI both ways   asymmetry is real and common -- a detuned antenna on one
 *                end, or a receiver desensitised by its own supply. From the
 *                transmitting side alone such a link looks perfect.
 *   SNR          the number that predicts whether a link survives rain and a
 *                full-length frame, which RSSI on its own does not.
 *
 * This module is the arithmetic and the report -- no ESP-IDF, no radio. Each
 * application owns its own radio and calls in with what came back, which is
 * what makes the summary host-testable.
 */
#ifndef RFTEST_H
#define RFTEST_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* A test long enough to be meaningful and short enough that somebody holding
 * a laptop in the rain waits for it. At SF9 a 64 B frame is ~200 ms of
 * airtime each way, so twenty round trips is about ten seconds. */
#define RFTEST_DEFAULT_COUNT   20
#define RFTEST_MAX_COUNT      500
/* How long to wait for one echo before calling it lost. Generous: a relay in
 * the path doubles the airtime, and a channel-busy backoff can add more. */
#define RFTEST_TIMEOUT_MS     3000

typedef struct {
    uint16_t sent;
    uint16_t echoed;
    /* Round trip, milliseconds, over the echoes that came back. */
    uint32_t rtt_min_ms, rtt_max_ms, rtt_sum_ms;
    /* What we heard from them, and what they heard from us. Summed as ints
     * because averaging dBm is only meaningful over one test at one place. */
    int32_t  rssi_here_sum, rssi_there_sum;
    int32_t  snr_here_sum_x4, snr_there_sum_x4;
    int8_t   rssi_here_worst, rssi_there_worst;
} rftest_stats_t;

void rftest_begin(rftest_stats_t *s);

/* One ping went out. */
void rftest_note_sent(rftest_stats_t *s);

/* One echo came back: the round trip, what we heard of them, what they heard
 * of us. SNR is in quarter-dB, as the radio and the wire format carry it. */
void rftest_note_echo(rftest_stats_t *s, uint32_t rtt_ms,
                      int8_t rssi_here, int8_t snr_here_x4,
                      int8_t rssi_there, int8_t snr_there_x4);

/* Loss as a percentage, 0..100. A test that sent nothing reports 100: no
 * evidence of a link is not evidence of a working one. */
uint8_t rftest_loss_pct(const rftest_stats_t *s);

/*
 * The verdict, in the words somebody commissioning a post needs.
 *
 * The thresholds are the ones that matter for THIS system rather than for
 * radios in general: a node reports once a minute and an alert must get
 * through first time, so a link losing one frame in ten is not "mostly fine",
 * it is a link that will drop an alert within the hour.
 */
typedef enum {
    RFTEST_NO_LINK = 0,   /* nothing came back at all                       */
    RFTEST_MARGINAL,      /* it works today and will not survive weather    */
    RFTEST_USABLE,        /* fine, with headroom worth having               */
    RFTEST_GOOD,
} rftest_verdict_t;

#define RFTEST_LOSS_MARGINAL_PCT   2    /* above this, not a deployable link */
#define RFTEST_LOSS_USABLE_PCT     0
#define RFTEST_SNR_MARGINAL_X4   (-2 * 4)  /* SF9 demodulates to about -15   */
#define RFTEST_SNR_GOOD_X4        (5 * 4)

rftest_verdict_t rftest_verdict(const rftest_stats_t *s);
const char *rftest_verdict_text(rftest_verdict_t v);

/* One line per number, printed to a caller-supplied buffer so the same
 * summary can go to a console, a log, or the gateway's web UI. */
void rftest_format(const rftest_stats_t *s, char *out, size_t cap);

#endif /* RFTEST_H */
