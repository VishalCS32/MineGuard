#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "sim800l.h"

static const char *TAG = "sim800l";

#define RX_BUF      2048
#define AT_REPLY    512

/* Read until `want` appears, "ERROR" appears, or the deadline passes. AT
 * replies are line-oriented and unsolicited messages arrive in the middle of
 * them, so matching on a substring of everything received is the only approach
 * that survives contact with a real modem. */
static bool wait_for(sim800l_t *m, const char *want, uint32_t timeout_ms,
                     char *out, size_t cap)
{
    char buf[AT_REPLY];
    size_t len = 0;
    int64_t deadline = esp_timer_get_time() + (int64_t)timeout_ms * 1000;

    memset(buf, 0, sizeof(buf));
    while (esp_timer_get_time() < deadline) {
        uint8_t ch;
        int n = uart_read_bytes(m->cfg.uart, &ch, 1, pdMS_TO_TICKS(50));
        if (n != 1) continue;
        if (len < sizeof(buf) - 1) buf[len++] = (char)ch;
        buf[len] = '\0';

        if (want && strstr(buf, want)) {
            if (out && cap) { strncpy(out, buf, cap - 1); out[cap - 1] = '\0'; }
            return true;
        }
        if (strstr(buf, "ERROR")) break;
    }
    if (out && cap) { strncpy(out, buf, cap - 1); out[cap - 1] = '\0'; }
    return false;
}

static bool at(sim800l_t *m, const char *cmd, const char *want,
               uint32_t timeout_ms, char *out, size_t cap)
{
    uart_flush_input(m->cfg.uart);
    uart_write_bytes(m->cfg.uart, cmd, strlen(cmd));
    uart_write_bytes(m->cfg.uart, "\r\n", 2);
    return wait_for(m, want ? want : "OK", timeout_ms, out, cap);
}

esp_err_t sim800l_power(sim800l_t *m, bool on)
{
    if (m->cfg.pwrkey == GPIO_NUM_NC) return ESP_OK;

    /* PWRKEY toggles: the same pulse turns it on and off, so the STATUS pin is
     * the only way to know which of the two just happened. Without STATUS wired
     * this call is a coin flip, which is why the caller checks for an AT reply
     * afterwards rather than trusting it. */
    if (m->cfg.status != GPIO_NUM_NC && gpio_get_level(m->cfg.status) == (on ? 1 : 0))
        return ESP_OK;

    gpio_set_level(m->cfg.pwrkey, 0);
    vTaskDelay(pdMS_TO_TICKS(1200));      /* datasheet: >1 s */
    gpio_set_level(m->cfg.pwrkey, 1);
    vTaskDelay(pdMS_TO_TICKS(on ? 3000 : 1500));
    return ESP_OK;
}

esp_err_t sim800l_init(sim800l_t *m, const sim800l_cfg_t *cfg)
{
    memset(m, 0, sizeof(*m));
    m->cfg = *cfg;
    m->last_csq = 99;

    if (cfg->pwrkey != GPIO_NUM_NC) {
        gpio_config_t io = { .pin_bit_mask = 1ULL << cfg->pwrkey,
                             .mode = GPIO_MODE_OUTPUT };
        ESP_ERROR_CHECK(gpio_config(&io));
        gpio_set_level(cfg->pwrkey, 1);
    }
    if (cfg->status != GPIO_NUM_NC) {
        gpio_config_t io = { .pin_bit_mask = 1ULL << cfg->status,
                             .mode = GPIO_MODE_INPUT };
        ESP_ERROR_CHECK(gpio_config(&io));
    }

    /* 9600 on purpose. The module autobauds and will happily sync at 115200,
     * then lose characters during a network burst when its own processor is
     * busy -- a corrupted AT reply looks like a failed send and gets retried,
     * which sends the message twice. */
    uart_config_t uc = {
        .baud_rate  = cfg->baud ? cfg->baud : 9600,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(cfg->uart, RX_BUF, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(cfg->uart, &uc));
    ESP_ERROR_CHECK(uart_set_pin(cfg->uart, cfg->tx, cfg->rx,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));

    /* Three tries at AT, powering the module up between them. A modem that has
     * just been given power needs a few seconds before it answers anything. */
    for (int attempt = 0; attempt < 3; attempt++) {
        if (at(m, "AT", "OK", 1000, NULL, 0)) { m->ready = true; break; }
        ESP_LOGW(TAG, "no answer to AT (attempt %d); toggling PWRKEY", attempt + 1);
        sim800l_power(m, true);
    }
    if (!m->ready) {
        ESP_LOGE(TAG, "modem not responding. Check the supply first: this part "
                      "needs 3.4-4.4 V and draws up to 2 A in bursts");
        return ESP_ERR_TIMEOUT;
    }

    at(m, "ATE0", "OK", 1000, NULL, 0);          /* no echo: replies get parsed */
    at(m, "AT+CMGF=1", "OK", 1000, NULL, 0);     /* SMS text mode, not PDU      */
    at(m, "AT+CSCS=\"GSM\"", "OK", 1000, NULL, 0);
    /* Route unsolicited messages to the serial port rather than storing them:
     * a full SIM message store makes the next send fail with no useful error. */
    at(m, "AT+CNMI=2,1,0,0,0", "OK", 1000, NULL, 0);

    int csq = 99;
    sim800l_check_network(m, &csq);
    ESP_LOGI(TAG, "up: %s, signal %d/31",
             m->registered ? "registered" : "not registered yet", csq);
    return ESP_OK;
}

bool sim800l_check_network(sim800l_t *m, int *csq_out)
{
    char reply[AT_REPLY];

    if (at(m, "AT+CSQ", "+CSQ:", 2000, reply, sizeof(reply))) {
        const char *p = strstr(reply, "+CSQ:");
        if (p) m->last_csq = atoi(p + 5);
    }
    if (csq_out) *csq_out = m->last_csq;

    if (!at(m, "AT+CREG?", "+CREG:", 2000, reply, sizeof(reply))) {
        m->registered = false;
        return false;
    }
    /* +CREG: <n>,<stat> -- 1 is registered on the home network, 5 is roaming.
     * Everything else means not yet, and on a cold modem "not yet" is the
     * normal answer for the first half minute. */
    const char *p = strstr(reply, "+CREG:");
    int stat = 0;
    if (p && sscanf(p, "+CREG: %*d,%d", &stat) == 1)
        m->registered = (stat == 1 || stat == 5);
    else
        m->registered = false;

    return m->registered;
}

/* Numbers arrive as one comma-separated NVS string; walk it without modifying
 * the caller's buffer. */
static const char *next_number(const char *list, char *out, size_t cap)
{
    while (*list == ' ' || *list == ',') list++;
    if (!*list) return NULL;

    size_t n = 0;
    while (*list && *list != ',' && n < cap - 1) {
        if (*list != ' ') out[n++] = *list;
        list++;
    }
    out[n] = '\0';
    return list;
}

int sim800l_send_sms(sim800l_t *m, const char *recipients, const char *text)
{
    if (!m->ready || !recipients || !*recipients || !text) return 0;

    if (!m->registered && !sim800l_check_network(m, NULL)) {
        /* Try anyway. Registration state read once can be stale, and a message
         * that might get through is worth ten seconds of modem time. */
        ESP_LOGW(TAG, "not registered; attempting the send regardless");
    }

    int accepted = 0;
    char number[24];
    const char *cursor = recipients;

    while ((cursor = next_number(cursor, number, sizeof(number))) != NULL) {
        if (number[0] == '\0') continue;

        char cmd[48];
        snprintf(cmd, sizeof(cmd), "AT+CMGS=\"%s\"", number);

        uart_flush_input(m->cfg.uart);
        uart_write_bytes(m->cfg.uart, cmd, strlen(cmd));
        uart_write_bytes(m->cfg.uart, "\r", 1);

        /* The modem answers with "> " and then swallows everything until a
         * Ctrl-Z. Sending the body before that prompt arrives loses the first
         * characters of the message. */
        if (!wait_for(m, ">", 5000, NULL, 0)) {
            ESP_LOGW(TAG, "no prompt for %s", number);
            m->failed++;
            uart_write_bytes(m->cfg.uart, "\x1B", 1);   /* ESC: abandon it */
            continue;
        }

        uart_write_bytes(m->cfg.uart, text, strlen(text));
        uart_write_bytes(m->cfg.uart, "\x1A", 1);       /* Ctrl-Z: send    */

        /* Up to 60 s: the modem holds the line while the network accepts the
         * message, and on a weak signal it uses most of that. */
        if (wait_for(m, "+CMGS:", 60000, NULL, 0)) {
            ESP_LOGI(TAG, "sent to %s", number);
            m->sent++;
            accepted++;
        } else {
            ESP_LOGE(TAG, "send to %s failed", number);
            m->failed++;
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }
    return accepted;
}
