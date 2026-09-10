/*
 * The gateway's own web UI -- one page, served from flash, no internet.
 *
 * Why a gateway needs a UI at all when there is a whole dashboard upstream:
 * the dashboard answers "what is the ground doing", and this answers "is this
 * box working", which is a different question asked by a different person at a
 * different moment. It is what somebody standing in the rain next to the
 * gateway can open on a phone to find out whether the field is reporting,
 * whether the backhaul is up, how deep the spool has grown, whether the modem
 * has signal -- and to configure a gateway that has never had a network to
 * join, without a laptop and a USB cable.
 *
 * It is reachable two ways, and the second is the point: over the site network
 * when there is one, and over the gateway's own access point when there is not.
 *
 * Deliberately small: one HTML file with inline CSS and JavaScript, no
 * framework, no CDN, no fonts. A page that fetches anything from the internet
 * is a page that is blank exactly where it is needed.
 */
#ifndef WEBUI_H
#define WEBUI_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "nodecfg.h"
#include "report.h"

typedef struct {
    /* Returns the number of recipients the modem accepted. */
    int (*test_sms)(const char *text);
} webui_hooks_t;

esp_err_t webui_start(nodecfg_t *cfg, const webui_hooks_t *hooks);

#endif /* WEBUI_H */
