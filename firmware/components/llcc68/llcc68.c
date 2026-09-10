#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "llcc68.h"

static const char *TAG = "llcc68";

/* -- opcodes ------------------------------------------------------------- */
#define CMD_SET_SLEEP              0x84
#define CMD_SET_STANDBY            0x80
#define CMD_SET_TX                 0x83
#define CMD_SET_RX                 0x82
#define CMD_SET_CAD                0xC5
#define CMD_SET_RF_FREQ            0x86
#define CMD_SET_PKT_TYPE           0x8A
#define CMD_SET_TX_PARAMS          0x8E
#define CMD_SET_PA_CONFIG          0x95
#define CMD_SET_BUF_BASE           0x8F
#define CMD_SET_MOD_PARAMS         0x8B
#define CMD_SET_PKT_PARAMS         0x8C
#define CMD_SET_CAD_PARAMS         0x88
#define CMD_SET_DIO_IRQ            0x08
#define CMD_GET_IRQ_STATUS         0x12
#define CMD_CLR_IRQ_STATUS         0x02
#define CMD_SET_DIO2_RF_SWITCH     0x9D
#define CMD_SET_DIO3_TCXO          0x97
#define CMD_SET_REGULATOR          0x96
#define CMD_CALIBRATE              0x89
#define CMD_CALIBRATE_IMAGE        0x98
#define CMD_WRITE_REG              0x0D
#define CMD_READ_REG               0x1D
#define CMD_WRITE_BUFFER           0x0E
#define CMD_READ_BUFFER            0x1E
#define CMD_GET_RX_BUF_STATUS      0x13
#define CMD_GET_PKT_STATUS         0x14
#define CMD_GET_RSSI_INST          0x15

#define STANDBY_RC                 0x00
#define PKT_TYPE_LORA              0x01

/* -- IRQ bits ------------------------------------------------------------ */
#define IRQ_TX_DONE                0x0001
#define IRQ_RX_DONE                0x0002
#define IRQ_CRC_ERR                0x0040
#define IRQ_CAD_DONE               0x0080
#define IRQ_CAD_DETECTED           0x0100
#define IRQ_TIMEOUT                0x0200
#define IRQ_ALL                    0x03FF

/* -- registers ----------------------------------------------------------- */
#define REG_RX_GAIN                0x08AC
#define REG_OCP                    0x08E7
#define REG_LORA_SYNC_MSB          0x0740
#define REG_LORA_SYNC_LSB          0x0741
#define REG_TX_CLAMP               0x08D8
#define REG_RTC_CTRL               0x0902
#define REG_EVT_CLR                0x0944

#define XTAL_FREQ                  32000000UL
#define FREQ_STEP_NUM              33554432UL   /* 2^25 */

llcc68_cfg_t llcc68_default_cfg(void)
{
    return (llcc68_cfg_t){
        .host = SPI2_HOST,
        .freq_hz  = 866100000UL,   /* mid-band, inside India's 865-867 MHz ISM */
        .sf       = 9,
        .bw       = LLCC68_BW_125,
        .cr       = LLCC68_CR_4_5,
        .tx_dbm   = 22,
        .preamble = 8,
        .sync_word = 0x1424,       /* private network */
        .dio2_as_rf_switch = true,
        .use_tcxo = false,         /* E220-900M22S runs from a crystal */
        .tcxo_voltage = 0x02,
    };
}

/* -- low level ----------------------------------------------------------- */

/* The chip raises BUSY while it digests a command. Talking to it during that
 * window silently corrupts the next transaction, and the symptom is a radio
 * that "works but drops packets" -- so every access waits here first. */
static esp_err_t wait_busy(llcc68_t *r, uint32_t timeout_ms)
{
    int64_t deadline = esp_timer_get_time() + (int64_t)timeout_ms * 1000;
    while (gpio_get_level(r->cfg.busy)) {
        if (esp_timer_get_time() > deadline) {
            ESP_LOGE(TAG, "BUSY stuck high -- check wiring, reset and power");
            return ESP_ERR_TIMEOUT;
        }
        vTaskDelay(1);
    }
    return ESP_OK;
}

static esp_err_t xfer(llcc68_t *r, uint8_t opcode,
                      const uint8_t *tx, uint8_t *rx, size_t n)
{
    esp_err_t err = wait_busy(r, 100);
    if (err != ESP_OK) return err;

    uint8_t txbuf[1 + 32] = {0};
    uint8_t rxbuf[1 + 32] = {0};
    if (n > 32) return ESP_ERR_INVALID_SIZE;

    txbuf[0] = opcode;
    if (tx && n) memcpy(txbuf + 1, tx, n);

    spi_transaction_t t = {
        .length    = (1 + n) * 8,
        .tx_buffer = txbuf,
        .rx_buffer = rxbuf,
    };
    err = spi_device_polling_transmit(r->spi, &t);
    if (err != ESP_OK) return err;
    if (rx && n) memcpy(rx, rxbuf + 1, n);
    return ESP_OK;
}

static esp_err_t cmd(llcc68_t *r, uint8_t opcode, const uint8_t *args, size_t n)
{
    return xfer(r, opcode, args, NULL, n);
}

/* Status reads return one stale byte before the payload, hence the extra byte. */
static esp_err_t cmd_read(llcc68_t *r, uint8_t opcode, uint8_t *out, size_t n)
{
    uint8_t buf[1 + 8] = {0};
    if (n > 8) return ESP_ERR_INVALID_SIZE;
    esp_err_t err = xfer(r, opcode, buf, buf, n + 1);
    if (err != ESP_OK) return err;
    memcpy(out, buf + 1, n);
    return ESP_OK;
}

static esp_err_t write_reg(llcc68_t *r, uint16_t addr, uint8_t val)
{
    uint8_t a[3] = { (uint8_t)(addr >> 8), (uint8_t)addr, val };
    return cmd(r, CMD_WRITE_REG, a, sizeof(a));
}

static esp_err_t read_reg(llcc68_t *r, uint16_t addr, uint8_t *val)
{
    esp_err_t err = wait_busy(r, 100);
    if (err != ESP_OK) return err;
    uint8_t tx[5] = { CMD_READ_REG, (uint8_t)(addr >> 8), (uint8_t)addr, 0x00, 0x00 };
    uint8_t rx[5] = {0};
    spi_transaction_t t = { .length = sizeof(tx) * 8, .tx_buffer = tx, .rx_buffer = rx };
    err = spi_device_polling_transmit(r->spi, &t);
    if (err == ESP_OK) *val = rx[4];
    return err;
}

static esp_err_t write_buffer(llcc68_t *r, uint8_t offset, const uint8_t *data, uint8_t len)
{
    esp_err_t err = wait_busy(r, 100);
    if (err != ESP_OK) return err;
    uint8_t tx[2 + 255];
    tx[0] = CMD_WRITE_BUFFER;
    tx[1] = offset;
    memcpy(tx + 2, data, len);
    spi_transaction_t t = { .length = (size_t)(2 + len) * 8, .tx_buffer = tx };
    return spi_device_polling_transmit(r->spi, &t);
}

static esp_err_t read_buffer(llcc68_t *r, uint8_t offset, uint8_t *data, uint8_t len)
{
    esp_err_t err = wait_busy(r, 100);
    if (err != ESP_OK) return err;
    uint8_t tx[3 + 255] = {0};
    uint8_t rx[3 + 255] = {0};
    tx[0] = CMD_READ_BUFFER;
    tx[1] = offset;
    spi_transaction_t t = { .length = (size_t)(3 + len) * 8, .tx_buffer = tx, .rx_buffer = rx };
    err = spi_device_polling_transmit(r->spi, &t);
    if (err == ESP_OK) memcpy(data, rx + 3, len);
    return err;
}

static esp_err_t get_irq(llcc68_t *r, uint16_t *irq)
{
    uint8_t b[2] = {0};
    esp_err_t err = cmd_read(r, CMD_GET_IRQ_STATUS, b, 2);
    if (err == ESP_OK) *irq = (uint16_t)((b[0] << 8) | b[1]);
    return err;
}

static esp_err_t clear_irq(llcc68_t *r, uint16_t mask)
{
    uint8_t b[2] = { (uint8_t)(mask >> 8), (uint8_t)mask };
    return cmd(r, CMD_CLR_IRQ_STATUS, b, 2);
}

static esp_err_t set_standby(llcc68_t *r)
{
    uint8_t m = STANDBY_RC;
    return cmd(r, CMD_SET_STANDBY, &m, 1);
}

static esp_err_t set_packet_params(llcc68_t *r, uint8_t payload_len)
{
    uint8_t p[6] = {
        (uint8_t)(r->cfg.preamble >> 8), (uint8_t)r->cfg.preamble,
        0x00,             /* explicit (variable-length) header */
        payload_len,
        0x01,             /* CRC on -- belt and braces with our own CRC16 */
        0x00,             /* IQ not inverted */
    };
    return cmd(r, CMD_SET_PKT_PARAMS, p, sizeof(p));
}

/* -- init ---------------------------------------------------------------- */

static esp_err_t hard_reset(llcc68_t *r)
{
    gpio_set_direction(r->cfg.reset, GPIO_MODE_OUTPUT);
    gpio_set_level(r->cfg.reset, 0);
    vTaskDelay(pdMS_TO_TICKS(5));
    gpio_set_level(r->cfg.reset, 1);
    vTaskDelay(pdMS_TO_TICKS(10));
    return wait_busy(r, 1000);
}

esp_err_t llcc68_set_tx_power(llcc68_t *r, int8_t dbm)
{
    if (dbm > 22) dbm = 22;
    if (dbm < -9) dbm = -9;

    /* The +22 dBm PA configuration from the datasheet, with output level set by
     * SetTxParams. Over-current protection has to be raised to match, or the PA
     * current-limits and the range quietly halves. */
    uint8_t pa[4] = { 0x04, 0x07, 0x00, 0x01 };
    esp_err_t err = cmd(r, CMD_SET_PA_CONFIG, pa, sizeof(pa));
    if (err != ESP_OK) return err;
    err = write_reg(r, REG_OCP, 0x38);          /* 140 mA */
    if (err != ESP_OK) return err;

    uint8_t tp[2] = { (uint8_t)dbm, 0x04 };     /* 200 us ramp */
    err = cmd(r, CMD_SET_TX_PARAMS, tp, sizeof(tp));
    if (err == ESP_OK) r->cfg.tx_dbm = dbm;
    return err;
}

esp_err_t llcc68_init(llcc68_t *r, const llcc68_cfg_t *cfg)
{
    memset(r, 0, sizeof(*r));
    r->cfg = *cfg;

    if (!llcc68_check_sf_bw(cfg->sf, cfg->bw)) {
        /* Fail loudly. A silently-clamped spreading factor gives a radio that
         * appears configured and cannot talk to its neighbours. */
        ESP_LOGE(TAG, "SF%u at this bandwidth is outside the LLCC68's range "
                      "(BW125 tops out at SF9)", cfg->sf);
        return ESP_ERR_INVALID_ARG;
    }
    if (cfg->freq_hz < 865000000UL || cfg->freq_hz > 867000000UL)
        ESP_LOGW(TAG, "%.3f MHz is outside India's 865-867 MHz de-licensed band",
                 cfg->freq_hz / 1e6);

    gpio_config_t in = {
        .pin_bit_mask = (1ULL << cfg->busy) | (1ULL << cfg->dio1),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&in));

    spi_bus_config_t bus = {
        .mosi_io_num = cfg->mosi,
        .miso_io_num = cfg->miso,
        .sclk_io_num = cfg->sck,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        /* Far larger than any LoRa frame, and deliberately: on the gateway
         * this same bus carries the microSD card, whose sector transfers are
         * multi-kilobyte. Sizing the bus for the radio alone would make the
         * card mount fail with ESP_ERR_INVALID_SIZE. */
        .max_transfer_sz = 4096,
    };
    esp_err_t err = spi_bus_initialize(cfg->host, &bus, SPI_DMA_CH_AUTO);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) return err;

    spi_device_interface_config_t dev = {
        .clock_speed_hz = 8 * 1000 * 1000,
        .mode = 0,
        .spics_io_num = cfg->nss,
        .queue_size = 4,
    };
    err = spi_bus_add_device(cfg->host, &dev, &r->spi);
    if (err != ESP_OK) return err;

    err = hard_reset(r);
    if (err != ESP_OK) return err;

    ESP_ERROR_CHECK(set_standby(r));

    if (cfg->use_tcxo) {
        uint8_t t[4] = { cfg->tcxo_voltage, 0x00, 0x00, 0x64 };  /* 1 ms startup */
        ESP_ERROR_CHECK(cmd(r, CMD_SET_DIO3_TCXO, t, sizeof(t)));
        uint8_t cal = 0x7F;
        ESP_ERROR_CHECK(cmd(r, CMD_CALIBRATE, &cal, 1));
        vTaskDelay(pdMS_TO_TICKS(5));
    }
    if (cfg->dio2_as_rf_switch) {
        uint8_t on = 0x01;
        ESP_ERROR_CHECK(cmd(r, CMD_SET_DIO2_RF_SWITCH, &on, 1));
    }

    uint8_t reg_mode = 0x01;   /* DC-DC: markedly lower current than LDO */
    ESP_ERROR_CHECK(cmd(r, CMD_SET_REGULATOR, &reg_mode, 1));

    uint8_t pkt = PKT_TYPE_LORA;
    ESP_ERROR_CHECK(cmd(r, CMD_SET_PKT_TYPE, &pkt, 1));

    /* Image calibration for the 863-870 MHz band. */
    uint8_t img[2] = { 0xD7, 0xDB };
    ESP_ERROR_CHECK(cmd(r, CMD_CALIBRATE_IMAGE, img, sizeof(img)));

    uint32_t frf = (uint32_t)(((uint64_t)cfg->freq_hz * FREQ_STEP_NUM) / XTAL_FREQ);
    uint8_t f[4] = { (uint8_t)(frf >> 24), (uint8_t)(frf >> 16),
                     (uint8_t)(frf >> 8),  (uint8_t)frf };
    ESP_ERROR_CHECK(cmd(r, CMD_SET_RF_FREQ, f, sizeof(f)));

    /* Low data-rate optimisation is required when a symbol lasts longer than
     * 16.38 ms. At SF9/125 kHz a symbol is 4.1 ms, so it stays off. */
    uint32_t sym_us = (1000000UL << cfg->sf) /
                      (cfg->bw == LLCC68_BW_500 ? 500000UL :
                       cfg->bw == LLCC68_BW_250 ? 250000UL : 125000UL);
    uint8_t ldro = (sym_us > 16380) ? 1 : 0;
    uint8_t mod[4] = { cfg->sf, cfg->bw, cfg->cr, ldro };
    ESP_ERROR_CHECK(cmd(r, CMD_SET_MOD_PARAMS, mod, sizeof(mod)));

    ESP_ERROR_CHECK(set_packet_params(r, 255));

    uint8_t base[2] = { 0x00, 0x00 };
    ESP_ERROR_CHECK(cmd(r, CMD_SET_BUF_BASE, base, sizeof(base)));

    ESP_ERROR_CHECK(write_reg(r, REG_LORA_SYNC_MSB, (uint8_t)(cfg->sync_word >> 8)));
    ESP_ERROR_CHECK(write_reg(r, REG_LORA_SYNC_LSB, (uint8_t)cfg->sync_word));

    /* Boosted RX gain: ~2 dB of sensitivity for a little more current. On a node
     * that receives for milliseconds and sleeps for a minute, that trade is
     * obviously worth taking. */
    ESP_ERROR_CHECK(write_reg(r, REG_RX_GAIN, 0x96));

    /* Datasheet erratum: raise the TX clamp, or output power sags when the
     * antenna is mismatched -- which, on a hand-planted post, it always is. */
    uint8_t clamp = 0;
    if (read_reg(r, REG_TX_CLAMP, &clamp) == ESP_OK)
        ESP_ERROR_CHECK(write_reg(r, REG_TX_CLAMP, (uint8_t)(clamp | 0x1E)));

    ESP_ERROR_CHECK(llcc68_set_tx_power(r, cfg->tx_dbm));

    uint8_t irq[8] = {
        (uint8_t)(IRQ_ALL >> 8), (uint8_t)IRQ_ALL,   /* enable  */
        (uint8_t)(IRQ_ALL >> 8), (uint8_t)IRQ_ALL,   /* -> DIO1 */
        0, 0, 0, 0,
    };
    ESP_ERROR_CHECK(cmd(r, CMD_SET_DIO_IRQ, irq, sizeof(irq)));
    ESP_ERROR_CHECK(clear_irq(r, IRQ_ALL));

    r->ready = true;
    ESP_LOGI(TAG, "up: %.3f MHz SF%u BW%s CR4/%u %d dBm sync 0x%04X",
             cfg->freq_hz / 1e6, cfg->sf,
             cfg->bw == LLCC68_BW_500 ? "500" : cfg->bw == LLCC68_BW_250 ? "250" : "125",
             cfg->cr + 4, cfg->tx_dbm, cfg->sync_word);
    return ESP_OK;
}

/* -- transmit / receive -------------------------------------------------- */

esp_err_t llcc68_send(llcc68_t *r, const uint8_t *data, uint8_t len, uint32_t timeout_ms)
{
    if (!r->ready) return ESP_ERR_INVALID_STATE;

    ESP_ERROR_CHECK(set_standby(r));
    ESP_ERROR_CHECK(clear_irq(r, IRQ_ALL));
    ESP_ERROR_CHECK(set_packet_params(r, len));
    ESP_ERROR_CHECK(write_buffer(r, 0x00, data, len));

    uint8_t t[3] = { 0x00, 0x00, 0x00 };   /* no chip-side timeout; we time it */
    ESP_ERROR_CHECK(cmd(r, CMD_SET_TX, t, sizeof(t)));

    int64_t deadline = esp_timer_get_time() + (int64_t)timeout_ms * 1000;
    for (;;) {
        uint16_t irq = 0;
        if (get_irq(r, &irq) == ESP_OK) {
            if (irq & IRQ_TX_DONE) {
                clear_irq(r, IRQ_ALL);
                r->tx_count++;
                return ESP_OK;
            }
            if (irq & IRQ_TIMEOUT) {
                clear_irq(r, IRQ_ALL);
                return ESP_ERR_TIMEOUT;
            }
        }
        if (esp_timer_get_time() > deadline) {
            ESP_LOGW(TAG, "TX did not complete in %u ms", (unsigned)timeout_ms);
            set_standby(r);
            return ESP_ERR_TIMEOUT;
        }
        vTaskDelay(pdMS_TO_TICKS(2));
    }
}

esp_err_t llcc68_start_rx(llcc68_t *r)
{
    if (!r->ready) return ESP_ERR_INVALID_STATE;
    ESP_ERROR_CHECK(set_standby(r));
    ESP_ERROR_CHECK(clear_irq(r, IRQ_ALL));
    ESP_ERROR_CHECK(set_packet_params(r, 255));
    uint8_t t[3] = { 0xFF, 0xFF, 0xFF };   /* continuous */
    return cmd(r, CMD_SET_RX, t, sizeof(t));
}

esp_err_t llcc68_poll_rx(llcc68_t *r, uint8_t *buf, size_t cap, uint8_t *len)
{
    uint16_t irq = 0;
    esp_err_t err = get_irq(r, &irq);
    if (err != ESP_OK) return err;

    if (irq & IRQ_CRC_ERR) {
        /* Expected on a real link, not exceptional. Count it so the packet
         * delivery figure on the dashboard stays honest, then drop it. */
        r->crc_err_count++;
        clear_irq(r, IRQ_ALL);
        llcc68_start_rx(r);
        return ESP_ERR_INVALID_CRC;
    }
    if (!(irq & IRQ_RX_DONE)) return ESP_ERR_NOT_FOUND;

    uint8_t st[2] = {0};
    ESP_ERROR_CHECK(cmd_read(r, CMD_GET_RX_BUF_STATUS, st, 2));
    uint8_t plen = st[0], offset = st[1];
    if (plen > cap) plen = (uint8_t)cap;

    ESP_ERROR_CHECK(read_buffer(r, offset, buf, plen));

    uint8_t ps[3] = {0};
    if (cmd_read(r, CMD_GET_PKT_STATUS, ps, 3) == ESP_OK) {
        r->last_rssi_dbm = (int8_t)(-(int)ps[0] / 2);
        r->last_snr_x4   = (int8_t)ps[1];         /* SNR in quarter-dB */
    }

    *len = plen;
    r->rx_count++;
    clear_irq(r, IRQ_ALL);
    llcc68_start_rx(r);
    return ESP_OK;
}

esp_err_t llcc68_cad(llcc68_t *r, bool *detected, uint32_t timeout_ms)
{
    *detected = false;
    ESP_ERROR_CHECK(set_standby(r));
    ESP_ERROR_CHECK(clear_irq(r, IRQ_ALL));

    /* Symbol count, detect peak and min are the datasheet's recommendations for
     * this spreading factor; exit mode 0 returns to standby so the caller
     * decides what happens next. */
    uint8_t p[7] = { 0x02, (uint8_t)(r->cfg.sf + 13), 0x0A, 0x00, 0x00, 0x00, 0x00 };
    ESP_ERROR_CHECK(cmd(r, CMD_SET_CAD_PARAMS, p, sizeof(p)));
    ESP_ERROR_CHECK(cmd(r, CMD_SET_CAD, NULL, 0));

    int64_t deadline = esp_timer_get_time() + (int64_t)timeout_ms * 1000;
    for (;;) {
        uint16_t irq = 0;
        if (get_irq(r, &irq) == ESP_OK && (irq & IRQ_CAD_DONE)) {
            *detected = (irq & IRQ_CAD_DETECTED) != 0;
            clear_irq(r, IRQ_ALL);
            return ESP_OK;
        }
        if (esp_timer_get_time() > deadline) {
            clear_irq(r, IRQ_ALL);
            set_standby(r);
            return ESP_ERR_TIMEOUT;
        }
        vTaskDelay(1);
    }
}

esp_err_t llcc68_sleep(llcc68_t *r, bool warm_start)
{
    /* Warm start keeps the configuration in retention, so waking costs a few
     * hundred microseconds instead of a full re-init. */
    uint8_t mode = warm_start ? 0x04 : 0x00;
    return cmd(r, CMD_SET_SLEEP, &mode, 1);
}

esp_err_t llcc68_rssi_inst(llcc68_t *r, int16_t *dbm)
{
    uint8_t b = 0;
    esp_err_t err = cmd_read(r, CMD_GET_RSSI_INST, &b, 1);
    if (err == ESP_OK) *dbm = (int16_t)(-(int)b / 2);
    return err;
}
