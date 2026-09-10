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
 * energy budget, so it is switched, not just told to idle. */
#define PIN_GNSS_EN        21

/* Battery sense. ADC1, through a 100k/100k divider, so a 4.2 V cell reads
 * 2.1 V -- inside the 11 dB attenuated range with headroom. The divider is
 * gated by a MOSFET on PIN_VBAT_EN so it does not draw 21 uA continuously,
 * which over a season is a meaningful fraction of the battery it measures. */
#define PIN_VBAT_ADC       7
#define PIN_VBAT_EN        1     /* -1 if the divider is left permanently on */
#define VBAT_DIVIDER_X100  200   /* 2.00x: 100k over 100k                    */

#define PIN_STATUS_LED     2

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
 *      GPIO8  LIS3DH SDA    ->    SIM800L STATUS  (input)
 *      GPIO9  LIS3DH SCL    ->    microSD CS
 *      GPIO17 GNSS RX       ->    SIM800L RXD     (ESP TX, via divider)
 *      GPIO18 GNSS TX       ->    SIM800L TXD     (ESP RX)
 *      GPIO21 GNSS power    ->    SIM800L PWRKEY
 *      GPIO7  battery sense ->    supply rail sense (different divider)
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
 * through a divider or the module's RX pin sits above its absolute maximum. */
#define PIN_SIM_TX         17    /* ESP32 TX -> SIM800L RXD, via divider     */
#define PIN_SIM_RX         18    /* ESP32 RX <- SIM800L TXD, direct          */
/* PWRKEY is pulled low for ~1.2 s to toggle power. Drive it through an NPN or
 * an open-drain output: the pin idles at the module's own 4 V rail. */
#define PIN_SIM_PWRKEY     21
#define PIN_SIM_STATUS     8     /* high once the modem is up                */

/* Supply sense: the 12 V solar/battery rail through a 100k/22k divider. ADC1,
 * because ADC2 is unavailable whenever WiFi is running -- which on a gateway is
 * always, and the reading would fail exactly when the gateway is working. */
#define PIN_VBAT_ADC       7
#define VBAT_DIVIDER_X100  555   /* 5.55x: (100k + 22k) / 22k                */

#define PIN_STATUS_LED     2

#endif /* BOARD_GATEWAY */

#endif /* BOARD_PINS_H */
