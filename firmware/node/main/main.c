/*
 * SUBSIDENCE-NET node -- ESP32-S3 + LIS3DH + vibration switch + NEO-6M + E220.
 *
 * One binary flashes to every board in the field; NVS decides which node it is
 * (see components/nodecfg). What the node does with its life:
 *
 *     wake -> sample -> extract -> decide -> transmit -> listen -> sleep
 *      ~2 s of that, once a minute, and 58 seconds at about 10 uA.
 *
 * Three properties of this loop are worth understanding before changing it.
 *
 * 1. THE DUTY CYCLE IS ALIGNED TO THE EPOCH, NOT TO BOOT.
 *    A node sleeps until the next multiple of sample_interval_s in absolute
 *    UTC, not for sample_interval_s from now. Every node in the field is
 *    therefore awake at the same moment, which is the only reason a flood works
 *    at all: a relay that is asleep when its neighbour transmits is not a relay.
 *    Nodes drift apart by their crystal error between syncs (~20 ppm, ~2 s a
 *    day), and the receive window is far wider than that.
 *
 * 2. AN EVENT DOES NOT WAIT FOR THE NEXT SLOT.
 *    Threshold breaches are transmitted the moment they are found, and the
 *    accelerometer and vibration switch can wake the node out of deep sleep to
 *    find them. That is the difference between an early-warning system and a
 *    logger with a 60-second sample rate.
 *
 * 3. THE NODE SENDS STATISTICS, NOT WAVEFORMS.
 *    Tilt, vibration RMS, dominant frequency and temperature are extracted here
 *    and shipped as 22 bytes. Sending raw accelerometer samples over LoRa is not
 *    arithmetically possible, and this reduction is what lets a whole field
 *    share one 125 kHz channel.
 */
#define BOARD_NODE

#include <math.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/rtc_io.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_sleep.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "battery.h"
#include "board_pins.h"
#include "gnss.h"
#include "lis3dh.h"
#include "llcc68.h"
#include "meshnet.h"
#include "mesh_proto.h"
#include "nodecfg.h"
#include "nodelogic.h"
#include "subnet_proto.h"

static const char *TAG = "node";

/* -- tuning ---------------------------------------------------------------- */

/* Raw accelerometer reads averaged into one frame. At 100 Hz that is a third of
 * a second of sampling, and it divides the LIS3DH's ~1 mg quantisation noise by
 * about six -- which is what brings the per-frame tilt error inside the ~50 mdeg
 * the error budget assumes. */
#define SAMPLE_BURST            32

/*
 * ON vib_peak_hz, WHICH THIS FIRMWARE REPORTS AS ZERO.
 *
 * The frame carries a field for the dominant vibration frequency, and an honest
 * value cannot be produced from the burst above: a dominant frequency needs an
 * FFT over a uniformly sampled window, and the duty-cycled reads in
 * lis3dh_read() are not uniformly spaced. Reporting a number derived from them
 * would be reporting a measurement that was not made, and the backend would
 * treat it as one.
 *
 * The path to filling it in is clear and deliberately not taken yet: configure
 * the LIS3DH's own FIFO in stream mode at 400 Hz, drain 256 samples in one
 * burst, and run a radix-2 FFT over them (~5 ms on an S3). That costs the node
 * roughly 0.6 s of extra awake time per cycle, which is affordable only on a
 * mains-powered node or on a node that is already awake because a vibration
 * event woke it. Until then the field stays zero and the dashboard shows it as
 * absent rather than as a reading.
 */

/* How long the node listens after transmitting. It covers the gateway's reply,
 * a downlink held for this node, and other nodes' frames that need relaying --
 * all three arrive in the same window because the whole field wakes together. */
#define RX_WINDOW_MS            1500

/* Ten cycles. GNSS costs ~45 mA for as long as its antenna is live, so a fix
 * every cycle would dominate the entire power budget to re-measure a position
 * that does not change. */
#define GNSS_EVERY_N_CYCLES     10
#define GNSS_TIMEOUT_MS         45000

/* Topology changes far more slowly than the ground does. */
#define NEIGHBOR_EVERY_N_CYCLES 5

/* Before transmitting, listen. Two nodes that wake together will otherwise
 * transmit together, and at SF9 a collision costs both frames. */
#define CAD_ATTEMPTS            4
#define CAD_BACKOFF_MAX_MS      120

/* A cold-booted board stays awake this long before the duty cycle starts, so an
 * operator can provision it over the console without racing a deep sleep. */
#define PROVISIONING_WINDOW_MS  20000

/* -- state that survives deep sleep ---------------------------------------- */

#define RTC_MAGIC 0x53554233u   /* "SUB3" */

/*
 * RTC memory is the node's only continuity. Everything a node knows that took
 * more than one cycle to learn lives here: its clock, its sequence numbers, and
 * the tilt history the rate trigger is computed from. Lose it and the node
 * becomes a device that reports instantaneous tilt and can never detect that it
 * is changing.
 */
typedef struct {
    uint32_t    magic;
    uint32_t    epoch_base;     /* UTC at the moment us_at_base was taken     */
    int64_t     us_at_base;
    bool        time_valid;
    uint16_t    tx_seq;
    uint32_t    cycles;
    uint32_t    boots;
    nodelogic_t logic;
    int32_t     last_lat_e7, last_lon_e7;
    bool        pos_reported;
    /* The fix quality from the last time the receiver was actually powered.
     * Carried across sleep so a cycle that does not run the GNSS can report
     * what is known rather than reporting "no fix" once a minute. */
    uint8_t     last_gnss_status;
} rtc_state_t;

static RTC_DATA_ATTR rtc_state_t g_rtc;

/* -- runtime handles ------------------------------------------------------- */

static nodecfg_t   g_cfg;
static llcc68_t    g_radio;
static lis3dh_t    g_accel;
static gnss_t      g_gnss;
static meshnet_t   g_mesh;
static i2c_master_bus_handle_t g_i2c;
static bool        g_have_accel, g_have_radio, g_have_gnss;
static gnss_fix_t  g_last_fix;

/* -- the clock -------------------------------------------------------------- */
/*
 * The node has no RTC crystal and no battery-backed clock. Time comes from a
 * TIME_SYNC downlink or a GNSS fix, and is carried across deep sleep by hand:
 * before sleeping we advance the anchor by exactly the sleep we asked for, so
 * the reading is right whether or not esp_timer's counter survived. Timestamps
 * are what every rate in the system is divided by, so a clock that silently
 * restarts at zero would not produce a wrong warning -- it would produce a
 * confident one.
 */
static uint32_t node_now(void)
{
    if (!g_rtc.time_valid) return 0;
    int64_t now_us = esp_timer_get_time();
    if (now_us < g_rtc.us_at_base) g_rtc.us_at_base = now_us;  /* counter restarted */
    return g_rtc.epoch_base + (uint32_t)((now_us - g_rtc.us_at_base) / 1000000);
}

static void node_set_time(uint32_t epoch, const char *source)
{
    if (epoch < 1735689600u) return;    /* before 2025: not a real timestamp */
    int32_t step = g_rtc.time_valid ? (int32_t)(epoch - node_now()) : 0;
    g_rtc.epoch_base = epoch;
    g_rtc.us_at_base = esp_timer_get_time();
    g_rtc.time_valid = true;
    ESP_LOGI(TAG, "clock set from %s: %lu (step %+ld s)", source,
             (unsigned long)epoch, (long)step);
}

/* -- radio ------------------------------------------------------------------ */

static bool radio_send(const uint8_t *frame, size_t len)
{
    if (!g_have_radio) return false;

    /* Channel activity detection, then a random backoff. The whole field wakes
     * on the same second, so without this the first frames of every cycle land
     * on top of each other. */
    for (int i = 0; i < CAD_ATTEMPTS; i++) {
        bool busy = false;
        if (llcc68_cad(&g_radio, &busy, 200) != ESP_OK) break;
        if (!busy) break;
        vTaskDelay(pdMS_TO_TICKS(10 + esp_random() % CAD_BACKOFF_MAX_MS));
    }

    esp_err_t err = llcc68_send(&g_radio, frame, (uint8_t)len, 4000);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "transmit failed: %s", esp_err_to_name(err));
        return false;
    }
    llcc68_start_rx(&g_radio);    /* back to listening: relays run continuously */
    return true;
}

static bool send_payload(uint8_t msg_type, uint16_t dst, const void *payload,
                         uint16_t len)
{
    uint8_t frame[SUBNET_MAX_FRAME];
    size_t n = subnet_frame_build(frame, sizeof(frame), msg_type, g_cfg.addr, dst,
                                  meshnet_next_seq(&g_mesh), MESH_DEFAULT_TTL, 0,
                                  payload, len);
    if (n == 0) {
        ESP_LOGE(TAG, "payload of %u B does not fit a frame", len);
        return false;
    }
    g_rtc.tx_seq = g_mesh.tx_seq;
    return radio_send(frame, n);
}

/* -- downlink --------------------------------------------------------------- */

static void handle_config_set(const subnet_frame_t *f)
{
    cfg_t incoming;
    memcpy(&incoming, f->payload, sizeof(incoming));

    uint8_t status = nodecfg_apply_downlink(&g_cfg, &incoming);

    /* The ACK echoes the hash, which is what closes the loop: the dashboard
     * shows a config as pending until a node proves it is running that exact
     * set of values, rather than assuming a frame that may never have been
     * heard. */
    cfg_ack_t ack = {
        .t_epoch = node_now(),
        .cfg_version = incoming.cfg_version,
        .cfg_hash = incoming.cfg_hash,
        .status = status,
    };
    send_payload(MSG_CONFIG_ACK, ADDR_GATEWAY, &ack, sizeof(ack));

    if (status == CFG_STATUS_APPLIED) {
        llcc68_set_tx_power(&g_radio, (int8_t)g_cfg.cfg.tx_power_dbm);
        g_mesh.relay_enabled = (g_cfg.cfg.flags & CFG_FLAG_RELAY_ENABLED) != 0;

        /* A one-shot recalibration: take the tilt we are reading now as the new
         * zero. For a node that has been legitimately re-planted -- without it
         * the node reports that disturbance as ground movement for ever. */
        if (g_cfg.cfg.flags & CFG_FLAG_RECALIBRATE) {
            lis3dh_sample_t s;
            if (g_have_accel && lis3dh_read(&g_accel, &s, SAMPLE_BURST) == ESP_OK) {
                g_cfg.cfg.tilt_offset_pitch = s.pitch_mdeg;
                g_cfg.cfg.tilt_offset_roll  = s.roll_mdeg;
            }
            g_cfg.cfg.flags &= (uint8_t)~CFG_FLAG_RECALIBRATE;
            g_cfg.cfg.cfg_hash = subnet_cfg_hash(&g_cfg.cfg);
            nodecfg_save(&g_cfg);
            nodelogic_reset(&g_rtc.logic);   /* the history describes the old pose */
            ESP_LOGI(TAG, "recalibrated: zero is now pitch %d roll %d mdeg",
                     g_cfg.cfg.tilt_offset_pitch, g_cfg.cfg.tilt_offset_roll);
        }
    }
}

static void handle_frame(uint8_t *buf, uint16_t len)
{
    subnet_frame_t f;
    subnet_err_t err = subnet_frame_parse(buf, len, &f);
    if (err != SUBNET_OK) {
        g_mesh.dropped_bad++;
        ESP_LOGD(TAG, "dropped a frame: %s", subnet_strerror(err));
        return;
    }

    /* Every frame heard is a link observed, relayed or not: that is where the
     * topology graph on the dashboard comes from. */
    uint8_t snr = (uint8_t)((g_radio.last_snr_x4 + 80) < 0 ? 0 :
                            (g_radio.last_snr_x4 + 80) > 255 ? 255 :
                            (g_radio.last_snr_x4 + 80));
    meshnet_note_neighbor(&g_mesh, f.src, g_radio.last_rssi_dbm, snr,
                          (uint32_t)(esp_timer_get_time() / 1000));

    meshnet_action_t action = meshnet_on_rx(&g_mesh, &f,
                                            (uint32_t)(esp_timer_get_time() / 1000));
    if (action == MESHNET_DROP) return;

    if (action == MESHNET_CONSUME || action == MESHNET_CONSUME_AND_RELAY) {
        switch (f.type) {
        case MSG_CONFIG_SET:
            handle_config_set(&f);
            break;
        case MSG_TIME_SYNC: {
            timesync_t ts;
            memcpy(&ts, f.payload, sizeof(ts));
            node_set_time(ts.t_epoch, "TIME_SYNC");
            break;
        }
        default:
            /* Another node's uplink, seen because we are a relay. Nothing to
             * consume; the relay branch below moves it along. */
            break;
        }
    }

    if (action == MESHNET_RELAY || action == MESHNET_CONSUME_AND_RELAY) {
        if (meshnet_prepare_relay(buf, len, &f)) radio_send(buf, len);
    }
}

/* Listen for `ms`, relaying and consuming whatever arrives. */
static void rx_window(uint32_t ms)
{
    if (!g_have_radio) { vTaskDelay(pdMS_TO_TICKS(ms)); return; }

    llcc68_start_rx(&g_radio);
    int64_t deadline = esp_timer_get_time() + (int64_t)ms * 1000;

    while (esp_timer_get_time() < deadline) {
        uint8_t buf[SUBNET_MAX_FRAME];
        uint8_t len = 0;
        esp_err_t err = llcc68_poll_rx(&g_radio, buf, sizeof(buf), &len);
        if (err == ESP_OK && len) handle_frame(buf, len);
        else if (err == ESP_ERR_NOT_FOUND) vTaskDelay(pdMS_TO_TICKS(5));
    }
}

/* -- sensing ---------------------------------------------------------------- */

static void maybe_read_gnss(bool force, uint8_t *gnss_status, bool *fix_valid)
{
    *gnss_status = GNSS_STATUS(GNSS_NO_FIX, 0);
    *fix_valid = false;

    if (!g_have_gnss || !(g_cfg.cfg.flags & CFG_FLAG_GNSS_ENABLED)) return;

    bool due = force
            || !g_rtc.time_valid                              /* need a clock  */
            || (g_rtc.cycles % GNSS_EVERY_N_CYCLES) == 0;
    if (!due) {
        /* Report the last known fix quality without powering the receiver.
         * `fix_valid` stays false: this is a remembered fix, not a current one,
         * and displacement must never be judged against a stale position. */
        *gnss_status = g_rtc.last_gnss_status;
        return;
    }

    gnss_fix_t fix;
    gnss_power(&g_gnss, true);
    esp_err_t err = gnss_acquire(&g_gnss, &fix, GNSS_TIMEOUT_MS);
    gnss_power(&g_gnss, false);        /* the single most important call here */

    *gnss_status = GNSS_STATUS(fix.fix, fix.sats);
    if (err != ESP_OK || !fix.valid) return;

    g_last_fix = fix;
    g_rtc.last_gnss_status = *gnss_status;
    *fix_valid = true;

    if (fix.t_epoch && !g_rtc.time_valid) node_set_time(fix.t_epoch, "GNSS");

    /* Position is static until something drags the node, so it is sent once at
     * commissioning and then only when it changes. Spending airtime every cycle
     * to retransmit a constant is airtime the telemetry needs. */
    float moved = g_rtc.pos_reported
        ? gnss_distance_m(g_rtc.last_lat_e7, g_rtc.last_lon_e7, fix.lat_e7, fix.lon_e7)
        : 1e9f;
    if (moved > 5.0f) {
        pos_t p = {
            .t_epoch = fix.t_epoch ? fix.t_epoch : node_now(),
            .lat_e7 = fix.lat_e7, .lon_e7 = fix.lon_e7,
            .alt_m = fix.alt_m, .h_acc_cm = fix.h_acc_cm,
            .gnss_status = *gnss_status,
        };
        if (send_payload(MSG_POSITION, ADDR_GATEWAY, &p, sizeof(p))) {
            g_rtc.last_lat_e7 = fix.lat_e7;
            g_rtc.last_lon_e7 = fix.lon_e7;
            g_rtc.pos_reported = true;
        }
    }
}

static void send_neighbor_report(void)
{
    uint8_t payload[MESH_MAX_PAYLOAD];
    uint16_t len = meshnet_build_neighbor_payload(
        &g_mesh, node_now(), payload, sizeof(payload),
        (uint32_t)(esp_timer_get_time() / 1000), 10u * 60u * 1000u);
    if (len) send_payload(MSG_NEIGHBOR, ADDR_GATEWAY, payload, len);
}

/* -- one duty cycle ---------------------------------------------------------- */

static void run_cycle(bool woke_on_impact)
{
    uint32_t relayed_before = g_mesh.relayed;
    lis3dh_sample_t s = {0};
    bool tilt_ok = g_have_accel &&
                   lis3dh_read(&g_accel, &s, SAMPLE_BURST) == ESP_OK && s.valid;

    uint16_t vbat = battery_read_mv();

    uint8_t gnss_status = GNSS_STATUS(GNSS_NO_FIX, 0);
    bool fix_valid = false;
    maybe_read_gnss(false, &gnss_status, &fix_valid);

    nodelogic_input_t in = {
        .t_epoch    = node_now(),
        .time_valid = g_rtc.time_valid,
        .pitch_mdeg = s.pitch_mdeg, .roll_mdeg = s.roll_mdeg,
        .tilt_valid = tilt_ok,
        .vib_rms_mg = s.vib_rms_mg, .vib_valid = tilt_ok,
        .vbat_mv    = vbat,
        .woke_on_impact = woke_on_impact,
        .fix_valid  = fix_valid,
        .lat_e7 = g_last_fix.lat_e7, .lon_e7 = g_last_fix.lon_e7,
    };
    nodelogic_out_t out;
    nodelogic_evaluate(&g_rtc.logic, &in, &g_cfg.cfg, &out);

    /* Events first, and before the telemetry frame: a breach must not queue
     * behind routine traffic. */
    for (uint8_t i = 0; i < out.n_events; i++) {
        ESP_LOGW(TAG, "EVENT 0x%02X severity %u: %ld (limit %ld)",
                 out.events[i].event_code, out.events[i].severity,
                 (long)out.events[i].value, (long)out.events[i].threshold);
        send_payload(MSG_EVENT, ADDR_GATEWAY, &out.events[i], sizeof(evt_t));
    }

    tlm_t t = {
        .t_epoch     = in.t_epoch,
        .pitch_mdeg  = s.pitch_mdeg,
        .roll_mdeg   = s.roll_mdeg,
        .vib_rms_mg  = s.vib_rms_mg,
        .vib_peak_hz = s.vib_peak_hz,
        .temp_c_x100 = s.temp_c_x100,
        .n_samples   = s.n_samples,
        .gnss_status = gnss_status,
        .vbat_mv     = vbat,
        /* Link quality of the last frame we heard. The gateway's own RSSI for
         * this frame is measured at the far end; this is the reverse direction,
         * and an asymmetric link shows up as the two disagreeing. */
        .rssi        = g_radio.last_rssi_dbm,
        .snr         = (uint8_t)((g_radio.last_snr_x4 + 80) < 0 ? 0 :
                                 (g_radio.last_snr_x4 + 80) > 255 ? 255 :
                                 (g_radio.last_snr_x4 + 80)),
        .flags       = out.flags,
    };
    /* Relayed *this cycle*, not ever: the flag describes what this node did for
     * the mesh in the window the frame covers, and a latched flag would make
     * every node look like a permanent relay after its first forward. */
    if (g_mesh.relayed > relayed_before) t.flags |= TLM_FLAG_RELAYED;

    /* Raw attitude goes on the wire, not the offset-corrected figure: the
     * backend measures against its own commissioning baseline and correcting
     * twice would zero the very signal being looked for. The offsets exist for
     * the node's own threshold checks. */
    send_payload(MSG_TELEMETRY, ADDR_GATEWAY, &t, sizeof(t));

    if (g_rtc.cycles % NEIGHBOR_EVERY_N_CYCLES == 0) send_neighbor_report();

    ESP_LOGI(TAG, "cycle %lu: tilt %u mdeg (%d,%d) rate %ld mdeg/h%s "
                  "vib %u mg temp %.2f C bat %u mV (%u%%) %s",
             (unsigned long)g_rtc.cycles, out.tilt_mdeg, s.pitch_mdeg, s.roll_mdeg,
             (long)out.tilt_rate_mdeg_h, out.rate_valid ? "" : " (not yet)",
             s.vib_rms_mg, s.temp_c_x100 / 100.0, vbat,
             nodelogic_battery_pct(vbat),
             g_rtc.time_valid ? "" : "[NO CLOCK]");

    g_rtc.cycles++;
}

/* -- sleep ------------------------------------------------------------------- */

/*
 * Seconds until the next slot boundary in absolute time. Aligning to the epoch
 * rather than counting from boot is what keeps the whole field awake in the
 * same window -- see the note at the top of this file.
 */
static uint32_t seconds_to_next_slot(uint32_t now, uint16_t interval_s)
{
    if (interval_s < 5) interval_s = 60;
    if (now == 0) return interval_s;               /* no clock: free-run */
    uint32_t next = ((now / interval_s) + 1u) * interval_s;
    uint32_t wait = next - now;
    /* A boundary that is already almost here would have the node sleep and wake
     * with no time to do anything in between, and the wake itself costs more
     * energy than the sleep saves. Skip to the following slot instead. */
    if (wait < 5) wait += interval_s;
    return wait;
}

static void enter_deep_sleep(uint32_t seconds)
{
    /* Arm the accelerometer's own motion interrupt. It watches at ~2 uA while
     * the ESP32 draws ~10 uA, so the fast path costs nothing to keep armed. */
    if (g_have_accel && (g_cfg.cfg.flags & CFG_FLAG_VIB_ENABLED))
        lis3dh_arm_wake_interrupt(&g_accel, g_cfg.cfg.vib_alert_mg);
    else if (g_have_accel)
        lis3dh_sleep(&g_accel);

    if (g_have_radio) llcc68_sleep(&g_radio, true);
    if (g_have_gnss)  gnss_power(&g_gnss, false);

    /* Hold the anchor forward across the sleep by exactly the interval asked
     * for. On wake the reading is then correct whether or not the microsecond
     * counter survived. */
    if (g_rtc.time_valid) {
        g_rtc.epoch_base = node_now() + seconds;
        g_rtc.us_at_base = esp_timer_get_time() + (int64_t)seconds * 1000000;
    }

    rtc_gpio_pulldown_en(PIN_LIS3DH_INT1);
    rtc_gpio_pulldown_en(PIN_VIB_INT);
    esp_sleep_enable_ext1_wakeup(NODE_EXT1_WAKE_MASK, ESP_EXT1_WAKEUP_ANY_HIGH);
    esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000ULL);

    ESP_LOGI(TAG, "sleeping %lu s (impact wakes us sooner)", (unsigned long)seconds);
    esp_deep_sleep_start();
}

/* -- bring-up ---------------------------------------------------------------- */

static void init_i2c(void)
{
    i2c_master_bus_config_t bus = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = PIN_I2C_SDA,
        .scl_io_num = PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,   /* the modules carry 4k7 too */
    };
    if (i2c_new_master_bus(&bus, &g_i2c) != ESP_OK) {
        ESP_LOGE(TAG, "I2C bus failed to start");
        g_i2c = NULL;
    }
}

static void init_radio(void)
{
    llcc68_cfg_t rc = llcc68_default_cfg();
    rc.host  = SPI2_HOST;
    rc.sck   = PIN_LORA_SCK;   rc.miso = PIN_LORA_MISO;
    rc.mosi  = PIN_LORA_MOSI;  rc.nss  = PIN_LORA_NSS;
    rc.busy  = PIN_LORA_BUSY;  rc.dio1 = PIN_LORA_DIO1;
    rc.reset = PIN_LORA_RST;
    rc.tx_dbm = (int8_t)g_cfg.cfg.tx_power_dbm;

    if (llcc68_init(&g_radio, &rc) == ESP_OK) {
        g_have_radio = true;
        llcc68_start_rx(&g_radio);
    } else {
        /* A node with no radio still samples and still logs to the console --
         * useful on the bench, and it makes a dead radio obvious rather than
         * looking like a node that has nothing to say. */
        ESP_LOGE(TAG, "radio did not come up; continuing without it");
    }
}

void app_main(void)
{
    esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    bool woke_on_impact = (cause == ESP_SLEEP_WAKEUP_EXT1);
    bool cold_boot = (cause != ESP_SLEEP_WAKEUP_TIMER && cause != ESP_SLEEP_WAKEUP_EXT1);

    if (g_rtc.magic != RTC_MAGIC || !nodelogic_valid(&g_rtc.logic)) {
        memset(&g_rtc, 0, sizeof(g_rtc));
        g_rtc.magic = RTC_MAGIC;
        nodelogic_reset(&g_rtc.logic);
        cold_boot = true;
    }
    g_rtc.boots++;

    nodecfg_load(&g_cfg);
    meshnet_init(&g_mesh, g_cfg.addr,
                 (g_cfg.cfg.flags & CFG_FLAG_RELAY_ENABLED) != 0);
    g_mesh.tx_seq = g_rtc.tx_seq;    /* sequence numbers continue across sleep */

    init_i2c();
    if (g_i2c) g_have_accel = (lis3dh_init(&g_accel, g_i2c, LIS3DH_ADDR_LOW) == ESP_OK);

    battery_cfg_t bat = {
        .adc_gpio = PIN_VBAT_ADC,
        .enable_gpio = PIN_VBAT_EN,
        .divider_x100 = VBAT_DIVIDER_X100,
    };
    battery_init(&bat);

    gnss_cfg_t gc = {
        .uart = UART_NUM_1, .tx = PIN_GNSS_TX, .rx = PIN_GNSS_RX,
        .power_en = PIN_GNSS_EN, .pps = PIN_GNSS_PPS, .baud = 9600,
    };
    g_have_gnss = (gnss_init(&g_gnss, &gc) == ESP_OK);

    init_radio();

    if (cold_boot) {
        nodecfg_cli_start(&g_cfg);
        nodecfg_print(&g_cfg);
        ESP_LOGI(TAG, "cold boot: console open for %d s before the duty cycle",
                 PROVISIONING_WINDOW_MS / 1000);
        /* Listening rather than idling: a TIME_SYNC may well arrive during the
         * provisioning window, and starting the duty cycle with a clock is
         * worth far more than starting it a few seconds earlier. */
        rx_window(PROVISIONING_WINDOW_MS);

        /* An unprovisioned board must not disappear into a sleep cycle: it is
         * on a bench with somebody trying to type at it. */
        if (!g_cfg.provisioned)
            ESP_LOGW(TAG, "UNPROVISIONED: staying awake. `set addr 0x0010` then `save`");
    }

    for (;;) {
        run_cycle(woke_on_impact);
        woke_on_impact = false;

        uint32_t sleep_s = seconds_to_next_slot(node_now(),
                                                g_cfg.cfg.sample_interval_s);

        /*
         * A node with no clock cannot align to anything and cannot compute a
         * rate, so its only job is to get a TIME_SYNC. It listens instead of
         * sleeping -- costing battery, which is the right trade for a node that
         * is otherwise producing timestamps nobody can use.
         */
        if (!g_rtc.time_valid) {
            ESP_LOGW(TAG, "no clock yet; listening for a TIME_SYNC");
            rx_window(30000);
            continue;
        }

        bool may_sleep = (g_cfg.cfg.flags & CFG_FLAG_DEEP_SLEEP) && g_cfg.provisioned;
        if (!may_sleep) {
            /*
             * The always-awake case, and it is not a fallback: a node wired to
             * mains or carrying a large panel is the field's relay backbone,
             * and a relay that sleeps is not a relay. It spends the whole
             * interval in receive.
             */
            uint32_t listen_ms = sleep_s * 1000;
            while (listen_ms > 0) {
                uint32_t chunk = listen_ms > 5000 ? 5000 : listen_ms;
                rx_window(chunk);
                listen_ms -= chunk;
            }
            continue;
        }

        /* Listen before sleeping: this window is when a gateway holding a
         * downlink for this node will send it, because a frame that has just
         * arrived is proof the node is awake. */
        rx_window(RX_WINDOW_MS);

        /* Recomputed after the window rather than adjusted for it. The cycle's
         * real duration varies -- a GNSS fix or a config downlink can add
         * seconds -- and sleeping for a fixed interval from a stale reading is
         * how a field's wake windows drift apart. */
        enter_deep_sleep(seconds_to_next_slot(node_now(),
                                              g_cfg.cfg.sample_interval_s));
    }
}
