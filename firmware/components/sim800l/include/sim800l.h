/*
 * SIM800L: the alerting path that does not depend on the internet.
 *
 * This is a 2G modem in 2026, which deserves a word of justification rather
 * than an apology. Indian coalfields have GSM coverage where they have no data
 * coverage at all, an SMS gets through at a signal level that would not sustain
 * a TCP handshake, and the message lands on a shift in-charge's ordinary phone
 * with no app installed and no network on it. For the one channel that has to
 * work at 3 a.m. when everything else is down, those properties beat bandwidth.
 *
 * POWER IS THE WHOLE DIFFICULTY WITH THIS PART, and most "the module keeps
 * restarting" reports are this and nothing else. It wants 3.4-4.4 V -- NOT the
 * 5 V rail and NOT 3.3 V -- and during a transmit burst it pulls up to 2 A for
 * about 600 us at the 2G frame rate. Off a linear regulator, or through thin
 * wire, the rail collapses, the module browns out mid-AT-command and reboots,
 * and the symptom looks exactly like a firmware bug. It needs its own buck
 * converter and a large bulk capacitor right at its pins; see docs/HARDWARE.md.
 *
 * The driver is deliberately blocking and slow. Sending one SMS takes seconds
 * and the gateway has a task to spare, so nothing here is worth the complexity
 * of an asynchronous AT parser.
 */
#ifndef SIM800L_H
#define SIM800L_H

#include <stdbool.h>
#include <stdint.h>

#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_err.h"

typedef struct {
    uart_port_t uart;
    gpio_num_t  tx, rx;
    gpio_num_t  pwrkey;    /* pulsed low to toggle power; GPIO_NUM_NC if tied */
    gpio_num_t  status;    /* high once the modem is running; GPIO_NUM_NC if unwired */
    int         baud;      /* 9600 is the reliable choice -- see the note below */
} sim800l_cfg_t;

typedef struct {
    sim800l_cfg_t cfg;
    bool     ready;
    bool     registered;
    int      last_csq;       /* 0..31, 99 = unknown                      */
    uint32_t sent, failed;
} sim800l_t;

/* Power the module up if necessary, wait for it to answer AT, and put it in
 * text mode. Returns ESP_ERR_TIMEOUT if the modem never answers -- which on
 * this part means the supply, nine times in ten. */
esp_err_t sim800l_init(sim800l_t *m, const sim800l_cfg_t *cfg);

/* Network registration, and the signal strength that explains it. Registration
 * takes 10-30 s from cold, so this is polled rather than waited on. */
bool sim800l_check_network(sim800l_t *m, int *csq_out);

/*
 * Send one message. `recipients` is the comma-separated E.164 list held in NVS
 * ("+919876543210,+911234567890"); each number is sent separately, because a
 * modem this old has no multi-recipient mode worth trusting.
 *
 * Returns the number of recipients the modem accepted. Partial success is
 * reported honestly: three numbers on the list and one text delivered is not
 * a failure, and it is not a success either.
 */
int sim800l_send_sms(sim800l_t *m, const char *recipients, const char *text);

/* Cut power. The modem idles at ~1 mA, which matters on a solar gateway
 * carrying it for a message it may send twice a week. */
esp_err_t sim800l_power(sim800l_t *m, bool on);

#endif /* SIM800L_H */
