/*
 * Battery sense.
 *
 * Small, but two details decide whether the number means anything:
 *
 *   ADC1, never ADC2. ADC2 shares hardware with the WiFi radio and returns
 *   errors whenever WiFi is up, so on the gateway a divider on an ADC2 pin
 *   reads zero exactly when the gateway is working.
 *
 *   Calibrated, not scaled. The raw ADC on an ESP32 is off by up to 6% and
 *   non-linear at the ends of its range; the eFuse calibration data turns that
 *   into millivolts good to about 1%. An uncalibrated reading would put the
 *   low-battery threshold anywhere within a couple of hundred millivolts, which
 *   on a lithium discharge curve is the difference between "warn next week" and
 *   "the node is about to stop".
 *
 * The divider is switched where the board allows it: 200k across a cell is
 * 21 uA continuously, which over a season is a few percent of the pack, spent
 * measuring the pack.
 */
#ifndef BATTERY_H
#define BATTERY_H

#include <stdbool.h>
#include <stdint.h>

#include "driver/gpio.h"
#include "esp_err.h"

typedef struct {
    gpio_num_t adc_gpio;      /* must be an ADC1 pin                         */
    gpio_num_t enable_gpio;   /* switches the divider; GPIO_NUM_NC if always on */
    uint16_t   divider_x100;  /* 200 = a 2.00x divider                       */
} battery_cfg_t;

esp_err_t battery_init(const battery_cfg_t *cfg);

/* Millivolts at the battery, averaged over a short burst. Returns 0 if the ADC
 * is unavailable -- reported as 0 in the frame rather than as a plausible
 * voltage, so the dashboard can tell the difference. */
uint16_t battery_read_mv(void);

#endif /* BATTERY_H */
