#include <stdio.h>

#include "statusled_pattern.h"

statusled_code_t statusled_evaluate(const statusled_input_t *in)
{
    /* Worst first. The order of these tests is the whole design: each one is
     * more disabling than the one below it. */

    /* Without a radio the gateway is a box with an internet connection and
     * nothing to say over it. */
    if (!in->radio_up) return LED_RADIO_DOWN;

    /* A radio that is up and hearing nothing means the field is gone -- every
     * node dead, or the antenna disconnected. Either is worse than losing the
     * backhaul, because the backhaul losing frames it never received is not
     * the problem. */
    if (in->uptime_s >= STATUSLED_SETTLE_S && in->quiet_s >= STATUSLED_QUIET_S)
        return LED_FIELD_SILENT;

    /* The modem is the path that works when everything else has failed;
     * losing it silently is how a site discovers at 3 a.m. that there is no
     * alerting at all. */
    if (!in->modem_ready || !in->modem_registered) return LED_NO_MODEM;

    if (!in->wifi_up)   return LED_NO_WIFI;
    if (!in->backend_ok) return LED_BACKEND_DOWN;

    /* Spooling is normal and expected; spooling this deep means the outage has
     * gone on long enough that data will start being shed. */
    if (in->spool_depth >= STATUSLED_SPOOL_DEEP) return LED_SPOOL_FILLING;

    return LED_OK;
}

uint8_t statusled_blinks(statusled_code_t code)
{
    switch (code) {
    case LED_RADIO_DOWN:    return 0;   /* continuous fast flash, not counted */
    case LED_FIELD_SILENT:  return 2;
    case LED_NO_MODEM:      return 3;
    case LED_NO_WIFI:       return 4;
    case LED_BACKEND_DOWN:  return 5;
    case LED_SPOOL_FILLING: return 6;
    case LED_OK:            return 1;
    default:                return 1;
    }
}

const char *statusled_tag(statusled_code_t code)
{
    switch (code) {
    case LED_RADIO_DOWN:    return "radio_down";
    case LED_FIELD_SILENT:  return "field_silent";
    case LED_NO_MODEM:      return "no_modem";
    case LED_NO_WIFI:       return "no_wifi";
    case LED_BACKEND_DOWN:  return "backend_down";
    case LED_SPOOL_FILLING: return "spool_filling";
    case LED_OK:            return "ok";
    default:                return "unknown";
    }
}

const char *statusled_meaning(statusled_code_t code)
{
    switch (code) {
    case LED_RADIO_DOWN:
        return "The radio did not start. Check the E220's wiring, its antenna "
               "and its supply -- nothing can be received until it does.";
    case LED_FIELD_SILENT:
        return "The radio is running but no node has been heard for three "
               "minutes. Check the gateway's antenna first, then the field.";
    case LED_NO_MODEM:
        return "No SIM800L, or it has no network. The offline SMS path is down: "
               "alerting now depends entirely on the backend being reachable.";
    case LED_NO_WIFI:
        return "Not joined to any site network. Frames are being spooled and "
               "local SMS still works. Join a network from this page.";
    case LED_BACKEND_DOWN:
        return "WiFi is up but the backend is not answering. Frames are being "
               "held and will be delivered when it returns; nothing is lost.";
    case LED_SPOOL_FILLING:
        return "The backlog is deep. The outage has lasted long enough that the "
               "oldest frames will start being shed.";
    case LED_OK:
        return "Receiving from the field and delivering to the backend.";
    default:
        return "";
    }
}

/*
 * Brightness. 24 is a clearly visible dot in daylight through a polycarbonate
 * lid and a comfortable one at night; the heartbeat runs dimmer still because
 * it is on every three seconds for the life of the installation.
 */
#define LIT   24
#define DIM   10

statusled_rgb_t statusled_colour(statusled_code_t code)
{
    switch (code) {
    /* Red: this gateway is not doing its job. */
    case LED_RADIO_DOWN:    return (statusled_rgb_t){ LIT, 0, 0 };
    case LED_FIELD_SILENT:  return (statusled_rgb_t){ LIT, 0, 0 };

    /* Amber: degraded, and nothing is being lost yet. */
    case LED_NO_MODEM:      return (statusled_rgb_t){ LIT, LIT / 2, 0 };
    case LED_NO_WIFI:       return (statusled_rgb_t){ LIT, LIT / 2, 0 };
    case LED_BACKEND_DOWN:  return (statusled_rgb_t){ LIT, LIT / 2, 0 };
    case LED_SPOOL_FILLING: return (statusled_rgb_t){ LIT, LIT / 2, 0 };

    /* Green, and dim: the state it will be in for months at a time. */
    case LED_OK:            return (statusled_rgb_t){ 0, DIM, 0 };
    default:                return (statusled_rgb_t){ DIM, DIM, DIM };
    }
}

/* Blue, and used for nothing else, so a flick is unmistakably traffic rather
 * than part of a fault code being counted. */
statusled_rgb_t statusled_frame_colour(void)
{
    return (statusled_rgb_t){ 0, 0, LIT };
}

void statusled_colour_hex(statusled_code_t code, char *out, size_t cap)
{
    statusled_rgb_t c = statusled_colour(code);
    /* Scaled back up for a screen: the panel is not being driven at the
     * brightness the LED is, and a #000a00 chip would look black. */
    unsigned scale = 255 / LIT;
    unsigned r = c.r * scale, g = c.g * scale, b = c.b * scale;
    if (r > 255) r = 255;
    if (g > 255) g = 255;
    if (b > 255) b = 255;
    snprintf(out, cap, "#%02x%02x%02x", r, g, b);
}
