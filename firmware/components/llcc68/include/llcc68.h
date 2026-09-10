/*
 * Ebyte E220-900M22S driver -- LLCC68 over SPI.
 *
 * The "M" in E220-900M22S matters: it exposes the LLCC68 die's own SPI bus, not
 * the "T" variant's UART transparent mode. There is no AUX pin and no
 * write-bytes-and-they-transmit shortcut; every setting is a register write. In
 * exchange we get per-packet RSSI and SNR (which the frame header carries),
 * per-frame control of spreading factor and power, and channel activity
 * detection -- which is what makes the wake-on-radio downlink path cheap enough
 * for a battery node.
 *
 * LLCC68 IS NOT AN SX1262. It is the cost-reduced part, and its spreading-factor
 * range is genuinely narrower:
 *
 *     BW 125 kHz  ->  SF5..SF9      <-- what this system uses
 *     BW 250 kHz  ->  SF5..SF10
 *     BW 500 kHz  ->  SF5..SF11
 *     SF12        ->  not supported at any bandwidth
 *
 * The link budget in ml/simulator/mesh.py is calibrated for SF9 at 125 kHz,
 * which is exactly the top of what this chip can do at that bandwidth. There is
 * no headroom to "just raise the spreading factor" if range disappoints in the
 * field: the moves available are antenna height, then bandwidth down to 250 kHz
 * with SF10, then more relays. llcc68_check_sf_bw() enforces this at runtime so
 * an impossible combination fails loudly at boot instead of producing a radio
 * that transmits into nothing.
 */
#ifndef LLCC68_H
#define LLCC68_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_err.h"

#include "llcc68_limits.h"   /* bandwidth codes and the SF/BW rule */

/* Coding rate */
#define LLCC68_CR_4_5  0x01
#define LLCC68_CR_4_6  0x02
#define LLCC68_CR_4_7  0x03
#define LLCC68_CR_4_8  0x04

typedef struct {
    spi_host_device_t host;
    gpio_num_t  sck, miso, mosi, nss;
    gpio_num_t  reset;
    gpio_num_t  busy;      /* the chip is not ready while this is high */
    gpio_num_t  dio1;      /* IRQ line */

    uint32_t    freq_hz;   /* 865000000..867000000 for the Indian ISM band */
    uint8_t     sf;        /* 5..9 at BW125 -- see the note above          */
    uint8_t     bw;        /* LLCC68_BW_*                                  */
    uint8_t     cr;        /* LLCC68_CR_*                                  */
    int8_t      tx_dbm;    /* -9..22                                       */
    uint16_t    preamble;  /* symbols; 8 is the usual choice               */
    uint16_t    sync_word; /* 0x1424 private, 0x3444 public                */

    /* Board wiring, and the two settings most often wrong on a new board. */
    bool        dio2_as_rf_switch;  /* most E220 boards: true              */
    bool        use_tcxo;           /* E220-900M22S is XTAL: false         */
    uint8_t     tcxo_voltage;       /* only when use_tcxo                  */
} llcc68_cfg_t;

typedef struct {
    llcc68_cfg_t     cfg;
    spi_device_handle_t spi;
    bool             ready;
    /* Link quality of the most recent packet, in the units the frame carries. */
    int8_t           last_rssi_dbm;
    int8_t           last_snr_x4;
    uint32_t         tx_count, rx_count, crc_err_count;
} llcc68_t;

/* Sensible defaults for this project: 866.1 MHz, SF9/125 kHz/4-5, 22 dBm. */
llcc68_cfg_t llcc68_default_cfg(void);

esp_err_t llcc68_init(llcc68_t *r, const llcc68_cfg_t *cfg);

/* Retune without a full re-init -- used when a config downlink changes power. */
esp_err_t llcc68_set_tx_power(llcc68_t *r, int8_t dbm);

/* Blocking transmit. `timeout_ms` bounds the wait for TxDone. */
esp_err_t llcc68_send(llcc68_t *r, const uint8_t *data, uint8_t len, uint32_t timeout_ms);

/* Park the radio in continuous receive. */
esp_err_t llcc68_start_rx(llcc68_t *r);

/*
 * Poll for a received packet. Returns ESP_OK and fills `len` when one is ready,
 * ESP_ERR_NOT_FOUND when nothing has arrived, ESP_ERR_INVALID_CRC when a packet
 * arrived corrupted (counted, then discarded -- never trust the radio).
 */
esp_err_t llcc68_poll_rx(llcc68_t *r, uint8_t *buf, size_t cap, uint8_t *len);

/*
 * Channel activity detection: is anyone transmitting right now?
 *
 * This is the cheap half of wake-on-radio. A node wakes, runs one CAD (a few
 * milliseconds and a few milliamps), and goes straight back to sleep unless
 * something is actually on the air -- instead of holding the receiver open for
 * the whole listen window at ~5 mA. Over a 60 s duty cycle that is the
 * difference between a node that runs for a season on a small panel and one
 * that does not.
 */
esp_err_t llcc68_cad(llcc68_t *r, bool *activity_detected, uint32_t timeout_ms);

/* Lowest-power state that retains configuration. */
esp_err_t llcc68_sleep(llcc68_t *r, bool warm_start);

/* Instantaneous RSSI, for a noise-floor check at commissioning. */
esp_err_t llcc68_rssi_inst(llcc68_t *r, int16_t *dbm);

#endif /* LLCC68_H */
