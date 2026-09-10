#include <string.h>

#include "driver/rmt_tx.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "statusled.h"

static const char *TAG = "statusled";

/*
 * WS2812B bit timing, from the datasheet, at a 10 MHz RMT resolution so one
 * tick is 0.1 us:
 *
 *   a 0 bit:  0.4 us high, 0.85 us low   ->  4 ticks, 8 ticks
 *   a 1 bit:  0.8 us high, 0.45 us low   ->  8 ticks, 4 ticks
 *
 * Both tolerate +/-150 ns, which the RMT hardware beats comfortably. The pixel
 * latches after >50 us of idle line, which the gap between our updates supplies
 * many times over.
 */
#define RMT_RESOLUTION_HZ  (10 * 1000 * 1000)
#define T0H 4
#define T0L 8
#define T1H 8
#define T1L 4

/* Timings. The blink is short and the pause is long: this sits on a pole all
 * night, and an indicator that is mostly on is both a nuisance and, on a solar
 * gateway in December, not free. */
#define BLINK_ON_MS      120
#define BLINK_OFF_MS     220
#define PAUSE_MS        1600
#define OK_FLASH_MS       60     /* the healthy heartbeat: ~2% duty cycle */
#define OK_PERIOD_MS    3000
#define FATAL_HALF_MS    100     /* continuous fast flash, unmistakable   */
#define FLICK_MS          25     /* one received frame                    */
#define FLICK_MIN_GAP_MS 250     /* or a busy field would hold it solid   */

static rmt_channel_handle_t s_chan;
static rmt_encoder_handle_t s_encoder;
static statusled_source_fn  s_source;
static statusled_code_t     s_code = LED_OK;
static volatile bool        s_frame_pending;
static int64_t              s_last_flick_us;

static void pixel(statusled_rgb_t c)
{
    if (!s_chan) return;

    /* Green, red, blue -- a WS2812 wants GRB, and getting it wrong gives an
     * indicator that is confidently the wrong colour. */
    const uint8_t bytes[3] = { c.g, c.r, c.b };
    rmt_symbol_word_t symbols[24];

    for (int i = 0; i < 3; i++) {
        for (int bit = 0; bit < 8; bit++) {
            bool one = (bytes[i] >> (7 - bit)) & 1;   /* MSB first */
            symbols[i * 8 + bit] = (rmt_symbol_word_t){
                .level0 = 1, .duration0 = one ? T1H : T0H,
                .level1 = 0, .duration1 = one ? T1L : T0L,
            };
        }
    }

    rmt_transmit_config_t tx = { .loop_count = 0 };
    if (rmt_transmit(s_chan, s_encoder, symbols, sizeof(symbols), &tx) == ESP_OK)
        rmt_tx_wait_all_done(s_chan, 50);
}

static void off(void)
{
    pixel((statusled_rgb_t){ 0, 0, 0 });
}

/* Sleep, but surface a received frame as a flick while waiting. The pause
 * between blink cycles is dead time otherwise, and it is exactly when there is
 * room to show traffic. */
static void idle_for(uint32_t ms)
{
    int64_t deadline = esp_timer_get_time() + (int64_t)ms * 1000;
    while (esp_timer_get_time() < deadline) {
        if (s_frame_pending) {
            s_frame_pending = false;
            int64_t now = esp_timer_get_time();
            if (now - s_last_flick_us > (int64_t)FLICK_MIN_GAP_MS * 1000) {
                s_last_flick_us = now;
                pixel(statusled_frame_colour());
                vTaskDelay(pdMS_TO_TICKS(FLICK_MS));
                off();
                continue;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

static void led_task(void *arg)
{
    (void)arg;
    statusled_code_t last_logged = LED_CODE_COUNT;

    for (;;) {
        statusled_input_t in = {0};
        if (s_source) s_source(&in);
        s_code = statusled_evaluate(&in);
        statusled_rgb_t colour = statusled_colour(s_code);

        /* Log transitions, not states: the console should record the moment a
         * gateway went wrong, not repeat every two seconds that it still is. */
        if (s_code != last_logged) {
            if (s_code == LED_OK)
                ESP_LOGI(TAG, "%s -- %s", statusled_tag(s_code), statusled_meaning(s_code));
            else
                ESP_LOGW(TAG, "%s (%u blinks) -- %s", statusled_tag(s_code),
                         statusled_blinks(s_code), statusled_meaning(s_code));
            last_logged = s_code;
        }

        if (s_code == LED_RADIO_DOWN) {
            /* Not counted: it should read as "broken" from across the yard. */
            for (int i = 0; i < 10; i++) {
                pixel(colour); vTaskDelay(pdMS_TO_TICKS(FATAL_HALF_MS));
                off();         vTaskDelay(pdMS_TO_TICKS(FATAL_HALF_MS));
            }
            continue;
        }

        if (s_code == LED_OK) {
            pixel(colour);
            vTaskDelay(pdMS_TO_TICKS(OK_FLASH_MS));
            off();
            idle_for(OK_PERIOD_MS - OK_FLASH_MS);
            continue;
        }

        uint8_t n = statusled_blinks(s_code);
        for (uint8_t i = 0; i < n; i++) {
            pixel(colour); vTaskDelay(pdMS_TO_TICKS(BLINK_ON_MS));
            off();         vTaskDelay(pdMS_TO_TICKS(BLINK_OFF_MS));
        }
        idle_for(PAUSE_MS);
    }
}

esp_err_t statusled_start(gpio_num_t pin, statusled_source_fn source)
{
    s_source = source;

    rmt_tx_channel_config_t chan_cfg = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .gpio_num = pin,
        .mem_block_symbols = 64,
        .resolution_hz = RMT_RESOLUTION_HZ,
        .trans_queue_depth = 4,
    };
    esp_err_t err = rmt_new_tx_channel(&chan_cfg, &s_chan);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "no RMT channel for the indicator: %s", esp_err_to_name(err));
        return err;
    }

    /* A copy encoder: the symbols are built above exactly as the pixel wants
     * them, so nothing needs encoding on the way out. */
    rmt_copy_encoder_config_t enc_cfg = {0};
    err = rmt_new_copy_encoder(&enc_cfg, &s_encoder);
    if (err != ESP_OK) return err;

    err = rmt_enable(s_chan);
    if (err != ESP_OK) return err;

    off();

    /* Lowest priority in the system. An indicator must never be the reason a
     * frame is missed. */
    if (xTaskCreate(led_task, "statusled", 3072, NULL, 1, NULL) != pdPASS) {
        ESP_LOGE(TAG, "could not start the indicator task");
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "onboard NeoPixel on GPIO%d", (int)pin);
    return ESP_OK;
}

void statusled_note_frame(void)
{
    s_frame_pending = true;
}

statusled_code_t statusled_current(void)
{
    return s_code;
}
