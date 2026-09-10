#include <math.h>
#include <string.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "lis3dh.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static const char *TAG = "lis3dh";

#define REG_STATUS_AUX  0x07
#define REG_OUT_TEMP_L  0x0C
#define REG_WHO_AM_I    0x0F
#define REG_TEMP_CFG    0x1F
#define REG_CTRL1       0x20
#define REG_CTRL2       0x21
#define REG_CTRL3       0x22
#define REG_CTRL4       0x23
#define REG_CTRL5       0x24
#define REG_OUT_X_L     0x28
#define REG_INT1_CFG    0x30
#define REG_INT1_SRC    0x31
#define REG_INT1_THS    0x32
#define REG_INT1_DUR    0x33

#define WHO_AM_I_VALUE  0x33
#define AUTO_INCREMENT  0x80

/* +/-2 g at 12-bit high resolution: 1 mg per LSB. The finest range the part
 * offers, and the right one -- a tilt sensor never sees more than 1 g. */
#define MG_PER_LSB      1.0f
#define SAMPLE_RATE_HZ  100

static esp_err_t wr(lis3dh_t *s, uint8_t reg, uint8_t val)
{
    uint8_t b[2] = { reg, val };
    return i2c_master_transmit(s->dev, b, sizeof(b), 100);
}

static esp_err_t rd(lis3dh_t *s, uint8_t reg, uint8_t *dst, size_t n)
{
    uint8_t r = (n > 1) ? (uint8_t)(reg | AUTO_INCREMENT) : reg;
    return i2c_master_transmit_receive(s->dev, &r, 1, dst, n, 100);
}

esp_err_t lis3dh_init(lis3dh_t *s, i2c_master_bus_handle_t bus, uint8_t addr)
{
    memset(s, 0, sizeof(*s));
    s->bus = bus;

    /* Try the requested address, then the other one. Boards wire SA0 both ways
     * and a node that refuses to boot over a strap is a node reporting nothing. */
    uint8_t candidates[2] = { addr, (addr == LIS3DH_ADDR_LOW) ? LIS3DH_ADDR_HIGH
                                                              : LIS3DH_ADDR_LOW };
    for (int i = 0; i < 2; i++) {
        i2c_device_config_t dc = {
            .dev_addr_length = I2C_ADDR_BIT_LEN_7,
            .device_address  = candidates[i],
            .scl_speed_hz    = 400000,
        };
        if (i2c_master_bus_add_device(bus, &dc, &s->dev) != ESP_OK) continue;

        uint8_t who = 0;
        if (rd(s, REG_WHO_AM_I, &who, 1) == ESP_OK && who == WHO_AM_I_VALUE) {
            s->addr = candidates[i];
            ESP_LOGI(TAG, "found at 0x%02X", s->addr);
            goto found;
        }
        i2c_master_bus_rm_device(s->dev);
        s->dev = NULL;
    }
    ESP_LOGE(TAG, "not responding at 0x18 or 0x19 -- check I2C wiring and pull-ups");
    return ESP_ERR_NOT_FOUND;

found:
    /* 100 Hz, all axes, high-resolution mode. */
    ESP_ERROR_CHECK(wr(s, REG_CTRL1, 0x57));
    ESP_ERROR_CHECK(wr(s, REG_CTRL4, 0x08));   /* +/-2 g, high resolution */
    ESP_ERROR_CHECK(wr(s, REG_TEMP_CFG, 0xC0));/* enable the temperature ADC */
    ESP_ERROR_CHECK(wr(s, REG_CTRL5, 0x40));   /* latch INT1 until read */
    vTaskDelay(pdMS_TO_TICKS(20));

    s->ready = true;
    return ESP_OK;
}

void lis3dh_vector_to_tilt(float ax, float ay, float az,
                           int16_t *pitch_mdeg, int16_t *roll_mdeg)
{
    /* Tilt from the gravity vector. atan2 against the magnitude of the other two
     * axes keeps both angles well-behaved through vertical, where a naive
     * atan(x/z) blows up. */
    float pitch = atan2f(ax, sqrtf(ay * ay + az * az)) * 180.0f / (float)M_PI;
    float roll  = atan2f(ay, sqrtf(ax * ax + az * az)) * 180.0f / (float)M_PI;

    float p = pitch * 1000.0f, r = roll * 1000.0f;
    /* Clamp rather than let the int16 wrap: a wrapped reading is a huge tilt of
     * the opposite sign, which reads as a catastrophe that is not happening. */
    if (p >  32767.0f) p =  32767.0f;
    if (p < -32768.0f) p = -32768.0f;
    if (r >  32767.0f) r =  32767.0f;
    if (r < -32768.0f) r = -32768.0f;
    *pitch_mdeg = (int16_t)p;
    *roll_mdeg  = (int16_t)r;
}

esp_err_t lis3dh_read(lis3dh_t *s, lis3dh_sample_t *out, uint8_t n_samples)
{
    memset(out, 0, sizeof(*out));
    if (!s->ready) return ESP_ERR_INVALID_STATE;
    if (n_samples == 0) n_samples = 1;

    double sx = 0, sy = 0, sz = 0;
    double sum_sq = 0;
    uint8_t got = 0;

    for (uint8_t i = 0; i < n_samples; i++) {
        uint8_t raw[6];
        if (rd(s, REG_OUT_X_L, raw, sizeof(raw)) != ESP_OK) continue;

        /* 12-bit left-justified in 16. */
        float x = (float)((int16_t)(raw[1] << 8 | raw[0]) >> 4) * MG_PER_LSB;
        float y = (float)((int16_t)(raw[3] << 8 | raw[2]) >> 4) * MG_PER_LSB;
        float z = (float)((int16_t)(raw[5] << 8 | raw[4]) >> 4) * MG_PER_LSB;

        sx += x; sy += y; sz += z;
        sum_sq += (double)x * x + (double)y * y + (double)z * z;
        got++;
        vTaskDelay(pdMS_TO_TICKS(1000 / SAMPLE_RATE_HZ));
    }
    if (got == 0) {
        ESP_LOGW(TAG, "no samples read");
        return ESP_FAIL;
    }

    float mx = (float)(sx / got), my = (float)(sy / got), mz = (float)(sz / got);
    lis3dh_vector_to_tilt(mx, my, mz, &out->pitch_mdeg, &out->roll_mdeg);

    /* Vibration is the RMS *about the mean* -- gravity is a constant 1 g and
     * would otherwise dominate the figure entirely. */
    double mean_sq = sum_sq / got;
    double dc_sq   = (double)mx * mx + (double)my * my + (double)mz * mz;
    double var     = mean_sq - dc_sq;
    if (var < 0) var = 0;
    double rms = sqrt(var);
    out->vib_rms_mg = (uint16_t)(rms > 65535.0 ? 65535.0 : rms);

    /* A dominant frequency needs an FFT over a uniformly sampled window; the
     * duty-cycled burst above is not that. Reported as 0 -- an honest absence,
     * not a fabricated number the backend would treat as a measurement.
     * See the note in node/main/main.c on running a real FFT when the node is
     * mains-powered or already awake for a vibration event. */
    out->vib_peak_hz = 0;

    uint8_t t[2] = {0};
    if (rd(s, REG_OUT_TEMP_L, t, sizeof(t)) == ESP_OK) {
        /* The LIS3DH temperature ADC is relative, not absolute: it reports
         * change from an unspecified reference. That is exactly what the drift
         * correction needs -- it subtracts a delta -- but it does mean the
         * offset is calibrated once at commissioning, not trusted from cold. */
        int16_t counts = (int16_t)((t[1] << 8) | t[0]) >> 6;
        out->temp_c_x100 = (int16_t)(counts * 100 + s->temp_offset_c_x100);
    }

    out->n_samples = got;
    out->valid = true;
    return ESP_OK;
}

esp_err_t lis3dh_arm_wake_interrupt(lis3dh_t *s, uint16_t threshold_mg)
{
    if (!s->ready) return ESP_ERR_INVALID_STATE;

    /* Threshold register is 7 bits at 16 mg per LSB in the +/-2 g range. */
    uint8_t ths = (uint8_t)(threshold_mg / 16);
    if (ths > 0x7F) ths = 0x7F;
    if (ths == 0)   ths = 1;

    ESP_ERROR_CHECK(wr(s, REG_CTRL3, 0x40));    /* IA1 -> INT1 pin            */
    ESP_ERROR_CHECK(wr(s, REG_INT1_THS, ths));
    ESP_ERROR_CHECK(wr(s, REG_INT1_DUR, 0x00)); /* fire on the first sample   */
    ESP_ERROR_CHECK(wr(s, REG_INT1_CFG, 0x2A)); /* OR of high events, XYZ     */

    uint8_t clear = 0;
    rd(s, REG_INT1_SRC, &clear, 1);             /* clear any latched event    */

    /* 10 Hz low-power mode: enough to catch an impact, ~2 uA while we sleep. */
    return wr(s, REG_CTRL1, 0x2F);
}

esp_err_t lis3dh_sleep(lis3dh_t *s)
{
    if (!s->ready) return ESP_OK;
    return wr(s, REG_CTRL1, 0x00);   /* power-down */
}
