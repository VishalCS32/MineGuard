#include <stdio.h>
#include <string.h>

#include "rftest.h"

void rftest_begin(rftest_stats_t *s)
{
    memset(s, 0, sizeof(*s));
    s->rtt_min_ms = UINT32_MAX;
    /* Worst-case trackers start at the best possible value so the first
     * sample replaces them. Starting at 0 would report a dead link as 0 dBm,
     * which reads as an excellent one. */
    s->rssi_here_worst = s->rssi_there_worst = 0;
}

void rftest_note_sent(rftest_stats_t *s)
{
    s->sent++;
}

void rftest_note_echo(rftest_stats_t *s, uint32_t rtt_ms,
                      int8_t rssi_here, int8_t snr_here_x4,
                      int8_t rssi_there, int8_t snr_there_x4)
{
    s->echoed++;
    s->rtt_sum_ms += rtt_ms;
    if (rtt_ms < s->rtt_min_ms) s->rtt_min_ms = rtt_ms;
    if (rtt_ms > s->rtt_max_ms) s->rtt_max_ms = rtt_ms;

    s->rssi_here_sum    += rssi_here;
    s->rssi_there_sum   += rssi_there;
    s->snr_here_sum_x4  += snr_here_x4;
    s->snr_there_sum_x4 += snr_there_x4;

    /* "Worst" is the most negative: RSSI is dBm below zero. */
    if (s->echoed == 1 || rssi_here  < s->rssi_here_worst)  s->rssi_here_worst  = rssi_here;
    if (s->echoed == 1 || rssi_there < s->rssi_there_worst) s->rssi_there_worst = rssi_there;
}

uint8_t rftest_loss_pct(const rftest_stats_t *s)
{
    if (s->sent == 0) return 100;
    uint32_t lost = (uint32_t)s->sent - s->echoed;
    return (uint8_t)((lost * 100u + s->sent / 2) / s->sent);
}

rftest_verdict_t rftest_verdict(const rftest_stats_t *s)
{
    if (s->echoed == 0) return RFTEST_NO_LINK;

    uint8_t loss = rftest_loss_pct(s);
    if (loss > RFTEST_LOSS_MARGINAL_PCT) return RFTEST_MARGINAL;

    /*
     * Both directions have to clear the bar, and the worse one decides. A
     * link that is loud outbound and deaf inbound is exactly the failure this
     * test exists to catch, and averaging the two directions together would
     * hide it behind the good one.
     */
    int32_t snr_here  = s->snr_here_sum_x4  / s->echoed;
    int32_t snr_there = s->snr_there_sum_x4 / s->echoed;
    int32_t snr = snr_here < snr_there ? snr_here : snr_there;

    if (snr < RFTEST_SNR_MARGINAL_X4) return RFTEST_MARGINAL;
    if (loss > RFTEST_LOSS_USABLE_PCT || snr < RFTEST_SNR_GOOD_X4) return RFTEST_USABLE;
    return RFTEST_GOOD;
}

const char *rftest_verdict_text(rftest_verdict_t v)
{
    switch (v) {
    case RFTEST_NO_LINK:
        return "NO LINK -- nothing came back. Antenna on both ends first, "
               "then range, then whether the far end is powered.";
    case RFTEST_MARGINAL:
        return "MARGINAL -- this link works today and will not survive rain "
               "or a full-length frame. Move the antenna or add a relay.";
    case RFTEST_USABLE:
        return "USABLE -- some headroom, but not much. Worth improving if "
               "the post is easy to reach.";
    case RFTEST_GOOD:
        return "GOOD -- deploy it.";
    default:
        return "";
    }
}

void rftest_format(const rftest_stats_t *s, char *out, size_t cap)
{
    if (!cap) return;

    if (s->echoed == 0) {
        snprintf(out, cap, "sent %u, echoed 0, loss 100%%\n  %s",
                 s->sent, rftest_verdict_text(RFTEST_NO_LINK));
        return;
    }

    /* Quarter-dB to tenths, so the report reads in the units a datasheet
     * uses rather than in the units the wire happens to carry. */
    int32_t snr_here  = (s->snr_here_sum_x4  * 10 / 4) / s->echoed;
    int32_t snr_there = (s->snr_there_sum_x4 * 10 / 4) / s->echoed;

    snprintf(out, cap,
             "sent %u, echoed %u, loss %u%%\n"
             "  rtt      %lu / %lu / %lu ms  (min/avg/max)\n"
             "  us->them %ld dBm avg, %d dBm worst, SNR %ld.%ld dB\n"
             "  them->us %ld dBm avg, %d dBm worst, SNR %ld.%ld dB\n"
             "  %s",
             s->sent, s->echoed, rftest_loss_pct(s),
             (unsigned long)s->rtt_min_ms,
             (unsigned long)(s->rtt_sum_ms / s->echoed),
             (unsigned long)s->rtt_max_ms,
             (long)(s->rssi_there_sum / s->echoed), s->rssi_there_worst,
             (long)(snr_there / 10), (long)(snr_there < 0 ? -snr_there % 10 : snr_there % 10),
             (long)(s->rssi_here_sum / s->echoed), s->rssi_here_worst,
             (long)(snr_here / 10), (long)(snr_here < 0 ? -snr_here % 10 : snr_here % 10),
             rftest_verdict_text(rftest_verdict(s)));
}
