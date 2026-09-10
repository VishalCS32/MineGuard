/*
 * LIS3DH: tilt, vibration and die temperature.
 *
 * This one chip supplies three of the four numbers in a telemetry frame, and the
 * third is the one people forget. Die temperature is not a weather reading --
 * it is the correction channel. The mounting post expands at roughly 18 mdeg of
 * apparent tilt per degree C, so an ordinary 15 C day moves the tilt reading by
 * five times the sensor's own noise, systematically, in a way averaging cannot
 * remove. Measured by the same die at the same instant, it subtracts cleanly.
 * Measured anywhere else, it does not correlate and corrects nothing.
 */
#ifndef LIS3DH_H
#define LIS3DH_H

#include <stdbool.h>
#include <stdint.h>

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_err.h"

/* SDO/SA0 low gives 0x18, high gives 0x19. Boards differ; both are tried. */
#define LIS3DH_ADDR_LOW   0x18
#define LIS3DH_ADDR_HIGH  0x19

typedef struct {
    i2c_master_bus_handle_t bus;
    i2c_master_dev_handle_t dev;
    uint8_t  addr;
    bool     ready;
    int16_t  temp_offset_c_x100;   /* one-point calibration from commissioning */
} lis3dh_t;

typedef struct {
    int16_t  pitch_mdeg;
    int16_t  roll_mdeg;
    uint16_t vib_rms_mg;
    uint16_t vib_peak_hz;
    int16_t  temp_c_x100;
    uint8_t  n_samples;      /* how many raw samples this average came from */
    bool     valid;
} lis3dh_sample_t;

esp_err_t lis3dh_init(lis3dh_t *s, i2c_master_bus_handle_t bus, uint8_t addr);

/*
 * Take one averaged measurement.
 *
 * `n_samples` raw reads are averaged for the attitude, which is what turns
 * ~1 mg of quantisation into the ~50 mdeg the error budget assumes. The same
 * burst yields the vibration RMS about the mean, so the node ships a statistic
 * rather than a waveform -- the whole reason 22 bytes a minute is enough.
 */
esp_err_t lis3dh_read(lis3dh_t *s, lis3dh_sample_t *out, uint8_t n_samples);

/*
 * Arm the accelerometer's own motion interrupt and let the node sleep.
 *
 * The LIS3DH keeps watching at ~2 uA while the ESP32 is in deep sleep, so an
 * impact or a blast wakes the node in milliseconds instead of waiting out the
 * duty cycle. This is the fast path behind EVT_VIBRATION and EVT_NODE_TAMPER.
 */
esp_err_t lis3dh_arm_wake_interrupt(lis3dh_t *s, uint16_t threshold_mg);

esp_err_t lis3dh_sleep(lis3dh_t *s);

/* Convert an acceleration vector to pitch and roll in milli-degrees. Pure maths,
 * exposed for the host tests. */
void lis3dh_vector_to_tilt(float ax, float ay, float az,
                           int16_t *pitch_mdeg, int16_t *roll_mdeg);

#endif /* LIS3DH_H */
