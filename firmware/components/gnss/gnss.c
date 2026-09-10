#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "gnss.h"

static const char *TAG = "gnss";
#define RX_BUF 1024

esp_err_t gnss_init(gnss_t *g, const gnss_cfg_t *cfg)
{
    memset(g, 0, sizeof(*g));
    g->cfg = *cfg;

    if (cfg->power_en != GPIO_NUM_NC) {
        gpio_config_t io = {
            .pin_bit_mask = 1ULL << cfg->power_en,
            .mode = GPIO_MODE_OUTPUT,
        };
        ESP_ERROR_CHECK(gpio_config(&io));
        gpio_set_level(cfg->power_en, 0);       /* start with it off */
    }

    uart_config_t uc = {
        .baud_rate = cfg->baud ? cfg->baud : 9600,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(cfg->uart, RX_BUF, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(cfg->uart, &uc));
    ESP_ERROR_CHECK(uart_set_pin(cfg->uart, cfg->tx, cfg->rx,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    return ESP_OK;
}

void gnss_power(gnss_t *g, bool on)
{
    if (g->cfg.power_en == GPIO_NUM_NC) { g->powered = true; return; }
    gpio_set_level(g->cfg.power_en, on ? 1 : 0);
    g->powered = on;
    if (on) vTaskDelay(pdMS_TO_TICKS(100));    /* let the regulator settle */
}

esp_err_t gnss_acquire(gnss_t *g, gnss_fix_t *out, uint32_t timeout_ms)
{
    memset(out, 0, sizeof(*out));
    out->fix = GNSS_NO_FIX;

    if (!g->powered) gnss_power(g, true);
    uart_flush_input(g->cfg.uart);

    char line[128];
    size_t len = 0;
    int64_t deadline = esp_timer_get_time() + (int64_t)timeout_ms * 1000;

    while (esp_timer_get_time() < deadline) {
        uint8_t ch;
        int n = uart_read_bytes(g->cfg.uart, &ch, 1, pdMS_TO_TICKS(200));
        if (n != 1) continue;

        if (ch == '\n' || ch == '\r') {
            if (len) {
                line[len] = '\0';
                gnss_parse_nmea(line, out);
                /* A 3-D fix with a real accuracy estimate is the bar for using
                 * a position at all -- a 2-D fix has no altitude, and altitude
                 * is the axis the whole system cares about. */
                if (out->valid && out->fix >= GNSS_FIX_3D && out->h_acc_cm > 0) {
                    ESP_LOGI(TAG, "fix: %.6f, %.6f  %u sats  +/-%.1f m",
                             out->lat_e7 / 1e7, out->lon_e7 / 1e7,
                             out->sats, out->h_acc_cm / 100.0);
                    return ESP_OK;
                }
                len = 0;
            }
            continue;
        }
        if (len < sizeof(line) - 1) line[len++] = (char)ch;
        else len = 0;               /* overlong garbage: resynchronise */
    }

    ESP_LOGW(TAG, "no usable fix in %u ms (%u sats seen) -- normal under cover",
             (unsigned)timeout_ms, out->sats);
    return ESP_ERR_TIMEOUT;
}
