/*
 * Board wiring -- the single source of truth for every pin in the system.
 *
 * Both applications include this file, and docs/HARDWARE.md is written from it.
 * A pin map that lives in three places is a pin map that disagrees with itself,
 * and the failure that follows is a node that boots, logs nothing wrong, and
 * reports garbage from a sensor that is not where the firmware thinks it is.
 *
 * Two boards:
 *
 *   NODE     ESP32-S3 mini      LIS3DH (I2C) + SW-420 vibration + NEO-6M (UART)
 *                               + E220-900M22S (SPI) + battery divider (ADC)
 *   GATEWAY  ESP32-S3 mini      the same board: E220-900M22S (SPI) + SIM800L
 *                               (UART) + microSD (SPI, sharing the radio's bus)
 *
 * Constraints that decided these choices, none of them arbitrary:
 *
 *  - EXT1 deep-sleep wake only works on RTC-capable GPIOs. On the ESP32-S3 that
 *    is GPIO0..21, so the two wake sources (the accelerometer's INT1 and the
 *    vibration sensor) must live in that range. This is the whole reason the
 *    node can respond to a blast in milliseconds instead of at its next slot.
 *  - ADC1 must be used, not ADC2: ADC2 is unavailable while WiFi is running, and
 *    on the gateway that would silently break the supply reading. ADC1 is
 *    GPIO1..10 on the S3.
 *  - Strapping pins (GPIO0, 3, 45, 46) are avoided for anything driven or
 *    loaded at boot. A divider hung on a strapping pin is a board that boots
 *    into the wrong mode maybe one time in five, which is the worst possible
 *    failure rate to debug.
 *  - GPIO19/20 are the native USB pins -- the console the boards are
 *    provisioned over -- and GPIO26..32 are SPI flash and PSRAM. Neither is
 *    available on any S3 module.
 *  - The gateway's SD card shares the radio's SPI bus with its own chip select.
 *    A second bus would cost four pins to buy nothing: the two devices are never
 *    accessed concurrently, and ESP-IDF serialises bus access anyway.
 */
#ifndef BOARD_PINS_H
#define BOARD_PINS_H

/* ------------------------------------------------------------------- NODE */
#if defined(BOARD_NODE)

/* LIS3DH -- I2C. 4.7k pull-ups to 3V3 on both lines (the module usually has
 * them; two modules on one bus means removing one set). */
#define PIN_I2C_SDA        8
#define PIN_I2C_SCL        9

/*
 * The two deep-sleep wake sources. Both MUST stay inside GPIO0..21: EXT1 wake
 * works only on RTC-capable pins, and on this board (which breaks out 1..18
 * and 21, with 21 taken by the pixel) every one of those is spoken for except
 * GPIO3, a strapping pin. There is no third option, so neither of these may
 * be moved to a high GPIO to make room for something else -- doing so does
 * not merely relocate the sensor, it silently removes the node's ability to
 * respond to a blast in milliseconds instead of at its next slot.
 */

/* Accelerometer interrupt: the LIS3DH watches for motion at ~2 uA while the
 * ESP32 is in deep sleep and pulls this line high when it sees an impact. */
#define PIN_LIS3DH_INT1    4

/* SW-420 / 801S vibration module, digital output. The second EXT1 wake source:
 * a mechanical switch costs no standing current at all, and catches the blast
 * that is too brief for the accelerometer's 10 Hz low-power sampling. */
#define PIN_VIB_INT        5

/* E220-900M22S -- LLCC68 over SPI2. */
#define PIN_LORA_MOSI      11
#define PIN_LORA_SCK       12
#define PIN_LORA_MISO      13
#define PIN_LORA_NSS       10
#define PIN_LORA_BUSY      14
#define PIN_LORA_DIO1      15
#define PIN_LORA_RST       16

/* NEO-6M -- UART1. TX/RX are named from the ESP32's point of view, so
 * PIN_GNSS_TX goes to the module's RX pin. Getting this backwards is the most
 * common wiring mistake on the whole board and it looks exactly like a dead
 * receiver. */
#define PIN_GNSS_TX        17
#define PIN_GNSS_RX        18
#define PIN_GNSS_PPS       6     /* optional; -1 if not wired               */
/* High-side load switch. The receiver draws ~45 mA whenever its antenna is
 * live, against ~10 uA for the sleeping ESP32 -- left powered it is the entire
 * energy budget, so it is switched, not just told to idle.
 *
 * GPIO2, not the GPIO21 an S3 pinout would suggest: on the ESP32-S3-Zero the
 * WS2812 owns GPIO21 and the pin is not brought out to a pad at all, so a
 * load switch there is not merely a conflict, it is a wire with nowhere to
 * land. GPIO2 is broken out, is not a strapping pin, and is inside the
 * RTC-capable range (GPIO0..21) -- which matters here: the level has to be
 * held through deep sleep, or the receiver powers itself back up the moment
 * the ESP32 stops driving the gate. */
#define PIN_GNSS_EN        2

/* Battery sense. ADC1, through a 100k/100k divider, so a 4.2 V cell reads
 * 2.1 V -- inside the 11 dB attenuated range with headroom. The divider is
 * gated by a MOSFET on PIN_VBAT_EN so it does not draw 21 uA continuously,
 * which over a season is a meaningful fraction of the battery it measures. */
#define PIN_VBAT_ADC       7
#define PIN_VBAT_EN        1     /* -1 if the divider is left permanently on */
#define VBAT_DIVIDER_X100  200   /* 2.00x: 100k over 100k                    */

/* The module's onboard WS2812, and left dark on purpose. Its controller draws
 * ~1 mA continuously even showing black -- fifty times a sleeping node's whole
 * budget, a third of its battery life spent on a light nobody is standing in
 * front of. Named here because GPIO21 is not a free pin to be spent elsewhere:
 * on this board it is not brought out at all. */
#define PIN_RGB_LED        21

/* Deep-sleep wake mask: either wake source pulls its pin high. */
#define NODE_EXT1_WAKE_MASK  ((1ULL << PIN_LIS3DH_INT1) | (1ULL << PIN_VIB_INT))

#endif /* BOARD_NODE */

/* ---------------------------------------------------------------- GATEWAY */
/*
 * The gateway is the SAME BOARD as a node -- an ESP32-S3 mini -- carrying
 * different modules on the same headers. That is worth stating plainly because
 * it is a decision, not a coincidence:
 *
 *   - One board to source, one board to spare. A field of 21 nodes and one
 *     gateway needs one kind of replacement in the van, not two.
 *   - The radio is wired identically on both, so the SPI half of the wiring is
 *     verified twenty-one times before the gateway is built.
 *   - Role is a value in NVS (`set role gateway`), never a compile-time
 *     constant, so a node can be turned into a gateway on site by swapping the
 *     modules and typing two commands.
 *
 * What changes is only what hangs off the other headers. Where a node has an
 * accelerometer, a vibration switch and a GNSS receiver, the gateway has a
 * microSD card and a 2G modem -- on the very same pins:
 *
 *      node                       gateway
 *      GPIO9  LIS3DH SCL    ->    microSD CS
 *      GPIO2  GNSS power    ->    SIM800L PWRKEY
 *      GPIO21 onboard RGB   ->    onboard RGB     (same pixel; lit only here)
 *
 * Four pins where the two roles genuinely diverge, because the gateway's
 * modem UART was moved off 17/18 -- those are wired to something else on the
 * gateway hardware -- and everything it displaced had to shift with it:
 *
 *      node                       gateway
 *      GPIO8  LIS3DH SDA    ->    SIM800L RXD     (ESP TX, via divider)
 *      GPIO7  battery sense ->    SIM800L TXD     (ESP RX)
 *      GPIO4  LIS3DH INT1   ->    supply rail sense (ADC1, different divider)
 *      GPIO17/18 GNSS UART  ->    free on the gateway
 */
#if defined(BOARD_GATEWAY)

/* E220-900M22S -- identical to the node, deliberately. */
#define PIN_LORA_MOSI      11
#define PIN_LORA_SCK       12
#define PIN_LORA_MISO      13
#define PIN_LORA_NSS       10
#define PIN_LORA_BUSY      14
#define PIN_LORA_DIO1      15
#define PIN_LORA_RST       16

/* microSD, sharing the radio's SPI bus with its own chip select. A second bus
 * would cost four pins to buy nothing: the two are never accessed at the same
 * moment and ESP-IDF serialises the bus regardless. */
#define PIN_SD_CS          9

/* SIM800L -- UART1. The module's logic is 2.8 V: its TX drives the ESP32
 * directly (2.8 V clears the 3.3 V input threshold), but the ESP32's TX must go
 * through a divider or the module's RX pin sits above its absolute maximum.
 *
 * On GPIO8/7 rather than the 17/18 a node uses for its GNSS. Any UART can be
 * routed to any GPIO through the S3's matrix, so the choice costs nothing --
 * but it does break the node/gateway pin symmetry on this pair, which is why
 * it is called out here and in the table above. 9600 baud is far below
 * anything the matrix cares about. */
#define PIN_SIM_TX         8     /* ESP32 TX -> SIM800L RXD, via divider     */
#define PIN_SIM_RX         7     /* ESP32 RX <- SIM800L TXD, direct          */
/*
 * PWRKEY and STATUS: -1, because the breakout in use does not have them.
 *
 * The common blue SIM800L board brings out seven pins -- VCC, GND, VDD, TXD,
 * RXD, GND, RESET -- and PWRKEY is tied on the board so the module starts as
 * soon as it has power. There is nothing to drive and nothing to read back.
 * The driver already treats both as optional; naming them -1 here is what
 * tells it so, and it stops the firmware reporting that it is "toggling
 * PWRKEY" at a pin that does not exist.
 *
 * What is lost is the ability to power-cycle a wedged modem in software, and
 * the ability to know it is up without asking it. On a board that has them,
 * set these to real GPIOs -- GPIO2 and GPIO6 are free and were their previous
 * home. RESET on this variant could serve the same purpose and the driver
 * does not use it yet.
 */
#define PIN_SIM_PWRKEY     -1
#define PIN_SIM_STATUS     -1    /* not brought out on this breakout         */

/* Supply sense: the 12 V solar/battery rail through a 100k/22k divider. ADC1,
 * because ADC2 is unavailable whenever WiFi is running -- which on a gateway is
 * always, and the reading would fail exactly when the gateway is working.
 *
 * GPIO4 rather than the node's GPIO7, which the modem's UART now occupies.
 * ADC1 is GPIO1..10 on the S3, so the replacement had to come from that range
 * -- 4 is inside it, is broken out, and is not a strapping pin. The driver
 * resolves the channel from the pin itself, so nothing else changes. */
#define PIN_VBAT_ADC       4
#define VBAT_DIVIDER_X100  555   /* 5.55x: (100k + 22k) / 22k                */

/*
 * The indicator: the addressable RGB pixel already fitted to the board -- no
 * LED, no resistor, no pad, nothing to wire. A WS2812 gives colour as well as
 * a blink count, which is what lets one light say both how bad it is and which
 * part is broken; see components/statusled and docs/HARDWARE.md 3.5.
 *
 * GPIO21 on the Waveshare ESP32-S3-Zero these boards are built from, and the
 * pin is not broken out to a pad -- it exists only as the pixel's DIN, which
 * is why nothing else may claim it. Other S3 boards put their pixel on 48
 * (DevKitC-1), 47, 38 or 8, and firmware cannot discover which; hence the
 * runtime override, `set led-pin 48` on the console. This value is only the
 * default, and if nothing lights up it is the first thing to try.
 *
 * The node has the same pixel on the same pin and deliberately leaves it dark:
 * a WS2812's controller draws ~1 mA even showing black, which is nothing on a
 * gateway with a panel and everything on a node running from a cell.
 */
#define PIN_RGB_LED        21

#endif /* BOARD_GATEWAY */

#endif /* BOARD_PINS_H */
