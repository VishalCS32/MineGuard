/*
 * The indicator driver: an onboard WS2812 ("NeoPixel"), driven from RMT.
 *
 * Written here rather than pulled from the component registry for the same
 * reason the LLCC68 driver is: it is sixty lines of well-documented timing, and
 * a build that reaches the internet to fetch a blink is a build that fails in a
 * site office with no internet.
 *
 * A WS2812 is not a GPIO LED. It wants a 24-bit stream where a bit is a pulse
 * whose *width* carries the value, at 800 kHz, with sub-microsecond tolerances
 * -- bit-banging it means disabling interrupts and still losing to WiFi. The
 * RMT peripheral clocks the waveform out in hardware, so the timing is exact
 * regardless of what the rest of the gateway is doing.
 *
 * ONE THING TO KNOW BEFORE COPYING THIS TO THE NODE: a WS2812's controller
 * draws roughly 1 mA continuously, even showing black, because the chip itself
 * is always powered. That is fifty times a sleeping node's entire budget and
 * would cut its battery life by a third. It belongs on the gateway, which has a
 * panel and a brick of a battery, and not on anything running from a cell.
 */
#ifndef STATUSLED_H
#define STATUSLED_H

#include <stdbool.h>

#include "driver/gpio.h"
#include "esp_err.h"

#include "statusled_pattern.h"

/* Called from the LED task to ask "what is true right now?". */
typedef void (*statusled_source_fn)(statusled_input_t *out);

/*
 * The same question, for a caller whose state does not look like a gateway's.
 * A node gathers its own inputs and runs statusled_evaluate_node() on them, so
 * the policy stays pure and host-tested while the driver stays ignorant of
 * which vocabulary it is rendering -- it only ever needs a colour and a count.
 */
typedef statusled_code_t (*statusled_code_fn)(void);

/*
 * `pin` is whichever GPIO the board's onboard pixel is wired to -- GPIO21 on
 * the Waveshare ESP32-S3-Zero this system is built from, GPIO48 on a
 * DevKitC-1, and 47, 38 or 8 on other variants. It is not discoverable, so it is a runtime value
 * (`set led-pin 48` on the console) defaulting to PIN_RGB_LED. If nothing lights up, that is the first thing to
 * change; see docs/HARDWARE.md 3.5.
 *
 * Starting sweeps the pixel red, green, blue and off, once. That is not
 * decoration: it is the only way an installer can tell "the LED is dark
 * because everything is fine" from "the LED is dark because it is on the wrong
 * pin", and it also proves the byte order -- a sweep that goes green, red,
 * blue means the pixel wants RGB rather than the GRB this driver sends.
 */
/*
 * Which order the pixel wants its three bytes in.
 *
 * Almost every WS2812 is GRB and that is the default. A few parts -- and a
 * few boards fitted with something WS2812-compatible rather than a WS2812 --
 * are RGB, and the symptom is specific and easy to misread: red and green
 * swap, so amber shows as a yellow-green and the healthy green heartbeat
 * shows as red. The boot sweep settles it in a second, since a sweep that
 * comes out GREEN, RED, BLUE is an RGB part being driven as GRB.
 */
typedef enum {
    STATUSLED_ORDER_GRB = 0,   /* the default, and nearly always right */
    STATUSLED_ORDER_RGB,
} statusled_order_t;

/* Call before starting. After the pixel is running this changes nothing --
 * the order is fixed at boot so the indicator cannot change meaning while
 * somebody is reading it. */
void statusled_set_order(statusled_order_t order);

esp_err_t statusled_start(gpio_num_t pin, statusled_source_fn source);

/*
 * Same driver, same pin rules, for a caller that resolves its own code -- the
 * node. Exactly one of the two may be started.
 */
esp_err_t statusled_start_code(gpio_num_t pin, statusled_code_fn source);

/* The GPIO the indicator actually came up on, or GPIO_NUM_NC if it did not.
 * Reported in the gateway's JSON so a board whose pixel is on the wrong pin
 * can be diagnosed from the web UI rather than by guessing. */
gpio_num_t statusled_pin(void);

/*
 * A frame just arrived. Produces a brief blue flick between blink cycles, which
 * is the single most useful thing this indicator does: standing next to the box
 * you can watch the mesh breathing, one flick per frame, with no equipment.
 */
void statusled_note_frame(void);

/* What the indicator is currently saying, for the JSON the web UI renders --
 * so a blink count read in the dark can be looked up on a phone. */
statusled_code_t statusled_current(void);

#endif /* STATUSLED_H */
