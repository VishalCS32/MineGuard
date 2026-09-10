#include <string.h>

#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "battery.h"

static const char *TAG = "battery";

#define SAMPLES 16

static adc_oneshot_unit_handle_t s_unit;
static adc_cali_handle_t         s_cali;
static adc_channel_t             s_channel;
static battery_cfg_t             s_cfg;
static bool                      s_ready;

esp_err_t battery_init(const battery_cfg_t *cfg)
{
    s_cfg = *cfg;
    s_ready = false;

    adc_unit_t unit;
    esp_err_t err = adc_oneshot_io_to_channel(cfg->adc_gpio, &unit, &s_channel);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "GPIO %d is not an ADC pin", (int)cfg->adc_gpio);
        return err;
    }
    if (unit != ADC_UNIT_1) {
        /* Refuse rather than work until WiFi comes up and then fail. */
        ESP_LOGE(TAG, "GPIO %d is on ADC2, which is unusable while WiFi runs",
                 (int)cfg->adc_gpio);
        return ESP_ERR_INVALID_ARG;
    }

    adc_oneshot_unit_init_cfg_t unit_cfg = { .unit_id = ADC_UNIT_1 };
    err = adc_oneshot_new_unit(&unit_cfg, &s_unit);
    if (err != ESP_OK) return err;

    /* 12 dB of attenuation puts full scale near 3.1 V, which is where a 2:1
     * divider on a 4.2 V cell lands with headroom to spare. */
    adc_oneshot_chan_cfg_t chan = {
        .atten    = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    err = adc_oneshot_config_channel(s_unit, s_channel, &chan);
    if (err != ESP_OK) return err;

#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED
    adc_cali_curve_fitting_config_t cali = {
        .unit_id = ADC_UNIT_1, .chan = s_channel,
        .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    if (adc_cali_create_scheme_curve_fitting(&cali, &s_cali) != ESP_OK) s_cali = NULL;
#elif ADC_CALI_SCHEME_LINE_FITTING_SUPPORTED
    adc_cali_line_fitting_config_t cali = {
        .unit_id = ADC_UNIT_1, .atten = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    if (adc_cali_create_scheme_line_fitting(&cali, &s_cali) != ESP_OK) s_cali = NULL;
#endif
    if (!s_cali)
        ESP_LOGW(TAG, "no eFuse calibration on this chip; readings are ~6%% raw");

    if (cfg->enable_gpio != GPIO_NUM_NC) {
        gpio_config_t io = { .pin_bit_mask = 1ULL << cfg->enable_gpio,
                             .mode = GPIO_MODE_OUTPUT };
        gpio_config(&io);
        gpio_set_level(cfg->enable_gpio, 0);
    }

    s_ready = true;
    return ESP_OK;
}

uint16_t battery_read_mv(void)
{
    if (!s_ready) return 0;

    if (s_cfg.enable_gpio != GPIO_NUM_NC) {
        gpio_set_level(s_cfg.enable_gpio, 1);
        vTaskDelay(pdMS_TO_TICKS(2));   /* let the divider and the ADC settle */
    }

    int total = 0, got = 0;
    for (int i = 0; i < SAMPLES; i++) {
        int raw = 0;
        if (adc_oneshot_read(s_unit, s_channel, &raw) != ESP_OK) continue;
        int mv = raw;
        if (s_cali && adc_cali_raw_to_voltage(s_cali, raw, &mv) != ESP_OK) continue;
        total += mv;
        got++;
    }

    if (s_cfg.enable_gpio != GPIO_NUM_NC) gpio_set_level(s_cfg.enable_gpio, 0);
    if (got == 0) return 0;

    uint32_t at_pin = (uint32_t)(total / got);
    uint32_t at_battery = at_pin * (s_cfg.divider_x100 ? s_cfg.divider_x100 : 100) / 100;
    return (uint16_t)(at_battery > 65535 ? 65535 : at_battery);
}
