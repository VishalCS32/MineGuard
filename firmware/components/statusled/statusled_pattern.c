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

statusled_code_t statusled_evaluate_node(const statusled_node_input_t *in)
{
    /* Worst first, same as the gateway's, and the order is again the design.
     * Everything here is about one question: can this node reach the field? */

    /* The module did not answer on SPI. Nothing this node measures will ever
     * leave the post, so it outranks every other thing that could be true. */
    if (!in->radio_up) return LED_NODE_RADIO_DOWN;

    /* It answered, and then would not send. Worth its own code rather than
     * being folded into "radio down": the two have completely different
     * causes -- that one is wiring, this one is almost always the antenna or
     * the supply sagging under a 22 dBm transmit. */
    if (!in->tx_ok) return LED_NODE_TX_FAILING;

    /* Heard nothing, ever. Out of range of the gateway and of every relay, or
     * the only antenna in earshot is missing -- but not before the settling
     * window is up, because the first frame a node can expect to hear is a
     * TIME_SYNC and that is on a ten-minute schedule. */
    if (in->heard_s == UINT32_MAX)
        return in->uptime_s >= STATUSLED_NODE_SETTLE_S ? LED_NODE_NO_MESH
                                                       : LED_NODE_OK;

    /* It was in the mesh and now is not. The node has moved, the gateway has
     * gone, or a relay between them has. */
    if (in->heard_s >= STATUSLED_NODE_QUIET_S) return LED_NODE_LINK_STALE;

    return LED_NODE_OK;
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

    case LED_NODE_RADIO_DOWN:  return 0;   /* continuous fast flash          */
    case LED_NODE_TX_FAILING:  return 2;
    case LED_NODE_NO_MESH:     return 3;
    case LED_NODE_LINK_STALE:  return 4;
    case LED_NODE_OK:          return 1;

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

    case LED_NODE_RADIO_DOWN:  return "node_radio_down";
    case LED_NODE_TX_FAILING:  return "node_tx_failing";
    case LED_NODE_NO_MESH:     return "node_no_mesh";
    case LED_NODE_LINK_STALE:  return "node_link_stale";
    case LED_NODE_OK:          return "node_ok";

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

    case LED_NODE_RADIO_DOWN:
        return "The LLCC68 did not answer on SPI. Check NSS, BUSY and NRST, "
               "then the module's supply -- nothing this node measures can "
               "leave the post until it does.";
    case LED_NODE_TX_FAILING:
        return "The radio initialised but transmits are not completing. "
               "Almost always the antenna, or the supply sagging under a "
               "22 dBm transmit.";
    case LED_NODE_NO_MESH:
        return "Transmitting, but nothing has ever been heard back. Out of "
               "range of the gateway and of every relay, or the antenna at "
               "the other end is missing.";
    case LED_NODE_LINK_STALE:
        return "This node was in the mesh and no longer is. The gateway has "
               "gone, or a relay between here and it has.";
    case LED_NODE_OK:
        return "Radio up, transmitting, and hearing the mesh.";

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

/*
 * Amber, weighted for the eye rather than for the arithmetic.
 *
 * The obvious amber is "red, plus half as much green", and it is wrong on a
 * WS2812. The three dice are not equally efficient: at the same drive the
 * green one puts out roughly twice the luminous intensity of the red, and the
 * eye is near its peak sensitivity at green's 525 nm and well down the curve
 * at red's 625 nm. Equal-looking needs unequal numbers. { LIT, LIT/2 } --
 * arithmetically two-thirds red -- lands perceptually around even, which
 * reads as a yellow-green, and at this brightness people call that green.
 *
 * A fifth as much green is what actually looks amber on this part. It is also
 * why the green heartbeat runs at DIM rather than LIT: the same efficiency
 * that ruins the mix makes plain green the brightest thing the pixel can do.
 */
#define AMBER_R  LIT
#define AMBER_G  (LIT / 5)

statusled_rgb_t statusled_colour(statusled_code_t code)
{
    switch (code) {
    /* Red: this gateway is not doing its job. */
    case LED_RADIO_DOWN:    return (statusled_rgb_t){ LIT, 0, 0 };
    case LED_FIELD_SILENT:  return (statusled_rgb_t){ LIT, 0, 0 };

    /* Amber: degraded, and nothing is being lost yet. */
    case LED_NO_MODEM:      return (statusled_rgb_t){ AMBER_R, AMBER_G, 0 };
    case LED_NO_WIFI:       return (statusled_rgb_t){ AMBER_R, AMBER_G, 0 };
    case LED_BACKEND_DOWN:  return (statusled_rgb_t){ AMBER_R, AMBER_G, 0 };
    case LED_SPOOL_FILLING: return (statusled_rgb_t){ AMBER_R, AMBER_G, 0 };

    /* Green, and dim: the state it will be in for months at a time. */
    case LED_OK:            return (statusled_rgb_t){ 0, DIM, 0 };

    /* A node's colours mean the same things, so somebody who has learned the
     * gateway's light can read a node's without being told twice. */
    case LED_NODE_RADIO_DOWN:  return (statusled_rgb_t){ LIT, 0, 0 };
    case LED_NODE_TX_FAILING:  return (statusled_rgb_t){ LIT, 0, 0 };
    case LED_NODE_NO_MESH:     return (statusled_rgb_t){ AMBER_R, AMBER_G, 0 };
    case LED_NODE_LINK_STALE:  return (statusled_rgb_t){ AMBER_R, AMBER_G, 0 };
    case LED_NODE_OK:          return (statusled_rgb_t){ 0, DIM, 0 };
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
