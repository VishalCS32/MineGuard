#include <stdio.h>
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

size_t gnss_raw_dump(gnss_t *g, uint32_t seconds, uint32_t *sentences_out)
{
    if (!g->powered) gnss_power(g, true);
    /* The module needs a moment after its rail comes up before it says
     * anything, and reporting "0 bytes" because we asked too early would be
     * the same false negative this function exists to prevent. */
    vTaskDelay(pdMS_TO_TICKS(500));
    uart_flush_input(g->cfg.uart);

    size_t bytes = 0;
    uint32_t sentences = 0, printable = 0;
    bool in_sentence = false;
    int64_t deadline = esp_timer_get_time() + (int64_t)seconds * 1000000;

    while (esp_timer_get_time() < deadline) {
        uint8_t ch;
        if (uart_read_bytes(g->cfg.uart, &ch, 1, pdMS_TO_TICKS(200)) != 1) continue;
        bytes++;
        if (ch >= 0x20 && ch < 0x7F) printable++;
        if (ch == '$') in_sentence = true;
        else if (ch == '\n' && in_sentence) { sentences++; in_sentence = false; }
        putchar((ch >= 0x20 && ch < 0x7F) || ch == '\n' ? (char)ch : '.');
    }
    fflush(stdout);

    if (sentences_out) *sentences_out = sentences;

    printf("\n-- %u bytes, %u NMEA sentences in %u s\n",
           (unsigned)bytes, (unsigned)sentences, (unsigned)seconds);
    if (bytes == 0) {
        printf("   NOTHING on the wire. This is not the sky.\n"
               "   Check, in this order: the module's TX goes to the ESP32's RX\n"
               "   (they cross -- pin names here are from the ESP32's side, and\n"
               "   getting it backwards looks exactly like a dead receiver);\n"
               "   then the module's supply; then the lead itself.\n");
    } else if (sentences == 0 || printable * 4 < bytes * 3) {
        printf("   Bytes arrive but are not NMEA -- that is a baud mismatch,\n"
               "   not a wiring fault. This driver opens the port at %u.\n",
               (unsigned)(g->cfg.baud ? g->cfg.baud : 9600));
    } else {
        printf("   The link is fine: sentences are arriving and being framed.\n"
               "   A missing fix is now genuinely the antenna, the sky, or a\n"
               "   cold start -- look for the satellite count in $GPGSV rising.\n");
    }
    return bytes;
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
