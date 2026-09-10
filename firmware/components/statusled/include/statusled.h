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
 * `pin` is whichever GPIO the board's onboard pixel is wired to -- GPIO48 on
 * most ESP32-S3 minis and DevKitC-1 boards, but a few use 38, 47 or 21. If
 * nothing lights up, that is the first thing to change; see docs/HARDWARE.md.
 */
esp_err_t statusled_start(gpio_num_t pin, statusled_source_fn source);

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
