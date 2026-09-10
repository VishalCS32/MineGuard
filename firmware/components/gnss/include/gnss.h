/*
 * NEO-6M GNSS: position, UTC, and nothing else.
 *
 * WHAT THIS IS NOT: a subsidence sensor. The receiver is accurate to metres and
 * subsidence is measured in millimetres -- three orders of magnitude apart, and
 * no amount of averaging closes that gap on a single-frequency receiver with no
 * carrier-phase output. Any claim that this hardware measures ground movement
 * would be false, and the API here is shaped so nobody can accidentally make it.
 *
 * WHAT IT IS FOR, all four of them real:
 *   1. Self-localisation. A node places itself on the map, so no operator has to
 *      walk the field dropping pins.
 *   2. UTC. Nodes have no RTC across deep sleep; a fix disciplines the clock and
 *      can retire the TIME_SYNC downlink entirely.
 *   3. The inter-node baselines. Strain is B*dT/dx -- something has to supply the
 *      dx, and metre accuracy over a 51 m spacing is a 2% error in strain.
 *   4. Gross displacement. A node that has moved metres is a collapse or a theft,
 *      and both are worth waking somebody for.
 *
 * POWER: the receiver draws tens of milliamps whenever its antenna is live,
 * against microamps for the ESP32 asleep. Left on it dominates the node's entire
 * budget. gnss_power() exists to be called with `false` far more often than
 * `true`.
 */
#ifndef GNSS_H
#define GNSS_H

#include <stdbool.h>
#include <stdint.h>

#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_err.h"

#include "gnss_nmea.h"   /* gnss_fix_t, gnss_parse_nmea, gnss_distance_m */

typedef struct {
    uart_port_t uart;
    gpio_num_t  tx, rx;
    gpio_num_t  power_en;   /* high-side switch; GPIO_NUM_NC if always powered */
    gpio_num_t  pps;        /* GPIO_NUM_NC if not wired                        */
    int         baud;       /* NEO-6M default is 9600                          */
} gnss_cfg_t;

typedef struct {
    gnss_cfg_t cfg;
    bool       powered;
} gnss_t;

esp_err_t gnss_init(gnss_t *g, const gnss_cfg_t *cfg);

/* Cut or restore power to the receiver. The single most important call here. */
void gnss_power(gnss_t *g, bool on);

/*
 * Wait for a fix, up to `timeout_ms`. Returns ESP_ERR_TIMEOUT if the sky was not
 * cooperative -- which is normal under overburden or tree cover, and is why the
 * node reports GNSS_NO_FIX in its telemetry rather than blocking on it.
 */
esp_err_t gnss_acquire(gnss_t *g, gnss_fix_t *out, uint32_t timeout_ms);

#endif /* GNSS_H */
