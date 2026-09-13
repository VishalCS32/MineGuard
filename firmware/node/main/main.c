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
#include <sys/time.h>
#include <time.h>

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
#include "rftest.h"
#include "statusled.h"
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

/*
 * What the indicator reads, when it is enabled. Both are boot-relative, and
 * that is the honest scope of a node's light: the LED task dies with the rest
 * of the chip at deep sleep, so what it can report is this wake period. On the
 * always-on relay and on the bench -- the two cases the light exists for --
 * the wake period is the whole run.
 */
static bool        g_tx_ok = true;      /* until a transmit says otherwise   */
static uint32_t    g_last_rx_ms;        /* 0 = nothing heard yet             */

/* -- the clock -------------------------------------------------------------- */
/*
 * The node has no RTC crystal and no battery-backed clock. Time comes from a
 * TIME_SYNC downlink or a GNSS fix, and is then held by the chip's own RTC
 * timer -- which keeps counting through deep sleep, so `time()` is still
 * right on the other side. Only `time_valid` needs carrying in RTC memory.
 *
 * THIS WAS CARRIED BY HAND AND THE HAND WAS WRONG. The previous version kept
 * its own epoch anchor and, before sleeping, advanced it by exactly the sleep
 * it had asked for. That is correct only if the sleep runs to term -- and the
 * whole point of this node is that it does not. EXT1 wakes it the instant the
 * ground moves, and the clock had already been credited the full interval. A
 * node with a lively vibration sensor therefore ran fast, permanently and
 * cumulatively: a few hundred impact wakes put one of these boards three and
 * a half hours into the future, and it filed every reading there.
 *
 * Timestamps are what every rate in the system is divided by, so this does
 * not produce a wrong warning -- it produces a confident one.
 */
static uint32_t node_now(void)
{
    if (!g_rtc.time_valid) return 0;
    return (uint32_t)time(NULL);
}

static void node_set_time(uint32_t epoch, const char *source)
{
    if (epoch < 1735689600u) return;    /* before 2025: not a real timestamp */
    int32_t step = g_rtc.time_valid ? (int32_t)(epoch - node_now()) : 0;

    struct timeval tv = { .tv_sec = (time_t)epoch, .tv_usec = 0 };
    settimeofday(&tv, NULL);
    /* Only the flag needs carrying by hand. The clock itself rides the RTC
     * timer, which keeps counting through deep sleep. */
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
    g_tx_ok = (err == ESP_OK);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "transmit failed: %s", esp_err_to_name(err));
        return false;
    }
    statusled_note_frame();       /* one flick of the pixel per frame sent   */
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

/* Defined with the rest of the link test, below the receive window it uses. */
static bool rf_handle(const subnet_frame_t *f);

static void handle_frame(uint8_t *buf, uint16_t len)
{
    subnet_frame_t f;
    subnet_err_t err = subnet_frame_parse(buf, len, &f);
    if (err != SUBNET_OK) {
        g_mesh.dropped_bad++;
        ESP_LOGD(TAG, "dropped a frame: %s", subnet_strerror(err));
        return;
    }

    /* Anything that parsed is proof the radio is hearing the mesh, whoever it
     * was addressed to. */
    g_last_rx_ms = (uint32_t)(esp_timer_get_time() / 1000);
    statusled_note_frame();

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
        /* Link-test frames are answered and go no further: they carry no
         * measurement and belong to whoever is standing at the other post. */
        if (rf_handle(&f)) return;

        switch (f.type) {
        case MSG_CONFIG_SET:
            handle_config_set(&f);
            break;
        case MSG_TIME_SYNC: {
            timesync_t ts;
            memcpy(&ts, f.payload, sizeof(ts));
            /* Epoch 0 is the gateway's presence beacon -- it is up and in
             * range but has no clock of its own yet. node_set_time() rejects
             * it as a timestamp; say so, because "the gateway is reachable
             * but the whole field is still unable to sleep" is a distinct
             * state from silence and looks the same without this line. */
            if (ts.t_epoch == 0)
                ESP_LOGI(TAG, "gateway heard (beacon, %d dBm) -- it has no "
                              "clock yet, so we still cannot sleep or align",
                         g_radio.last_rssi_dbm);
            else
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

/* How often the test loop pumps the receiver while waiting for an echo. */
#define RF_POLL_MS  20

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

/* -- RF link test ------------------------------------------------------------ */
/*
 * A ping, an echo, and the two numbers each end measured. See
 * components/rftest for why the echo carries the far end's RSSI: a link that
 * is loud outbound and deaf inbound is a real failure and looks perfect from
 * the transmitting side alone.
 *
 * The test is state rather than a loop that owns the radio, because on this
 * board it is not the console task that receives -- rx_window() does, from whichever task is pumping it. The
 * console sends and then waits for that path to set `got`.
 */
static rftest_stats_t    g_rft;
static volatile bool     g_rft_active;
static volatile uint32_t g_rft_want;      /* the ping sequence outstanding   */
static volatile bool     g_rft_got;
static volatile int8_t   g_rft_rssi_there, g_rft_snr_there;

/* Echo a ping straight back, at the same payload length, carrying what we
 * heard. Answered whether or not a test is running here: the other end is
 * commissioning a post and needs an answer, not a policy. */
static void rf_answer_ping(const subnet_frame_t *f)
{
    uint8_t pl[MESH_MAX_PAYLOAD];
    uint16_t n = f->payload_len > sizeof(pl) ? (uint16_t)sizeof(pl) : f->payload_len;
    if (n < sizeof(rf_test_t)) return;
    memcpy(pl, f->payload, n);

    rf_test_t r;
    memcpy(&r, pl, sizeof(r));
    r.rssi_dbm = g_radio.last_rssi_dbm;
    r.snr_x4   = g_radio.last_snr_x4;
    memcpy(pl, &r, sizeof(r));

    uint8_t frame[SUBNET_MAX_FRAME];
    size_t m = subnet_frame_build(frame, sizeof(frame), MSG_RF_PONG,
                                  g_cfg.addr, f->src,
                                  meshnet_next_seq(&g_mesh), MESH_DEFAULT_TTL, 0,
                                  pl, n);
    if (m) radio_send(frame, m);
}

static void rf_note_pong(const subnet_frame_t *f)
{
    if (!g_rft_active || f->payload_len < sizeof(rf_test_t)) return;
    rf_test_t r;
    memcpy(&r, f->payload, sizeof(r));
    if (r.seq != g_rft_want) return;      /* a late echo of an earlier ping */

    g_rft_rssi_there = r.rssi_dbm;
    g_rft_snr_there  = r.snr_x4;
    g_rft_got = true;
}

/* True if the frame was a link-test frame and needs nothing further done to
 * it. Kept in one place so both the ping and the echo leave by the same door. */
static bool rf_handle(const subnet_frame_t *f)
{
    if (f->type == MSG_RF_PING) { rf_answer_ping(f); return true; }
    if (f->type == MSG_RF_PONG) { rf_note_pong(f);   return true; }
    return false;
}

static bool rf_run_test(uint16_t dst, uint16_t count, uint8_t pad)
{
    if (!g_have_radio) return false;

    rftest_begin(&g_rft);
    g_rft_active = true;

    for (uint16_t i = 1; i <= count; i++) {
        uint8_t pl[MESH_MAX_PAYLOAD] = {0};
        uint16_t plen = (uint16_t)(sizeof(rf_test_t) + pad);
        uint32_t t0 = (uint32_t)(esp_timer_get_time() / 1000);

        rf_test_t r = { .seq = i, .t_ms = t0, .rssi_dbm = 0, .snr_x4 = 0 };
        memcpy(pl, &r, sizeof(r));

        g_rft_want = i;
        g_rft_got  = false;

        uint8_t frame[SUBNET_MAX_FRAME];
        size_t n = subnet_frame_build(frame, sizeof(frame), MSG_RF_PING,
                                      g_cfg.addr, dst,
                                      meshnet_next_seq(&g_mesh), MESH_DEFAULT_TTL, 0,
                                      pl, plen);
        if (!n || !radio_send(frame, n)) {
            /* A ping that never left is still a lost round trip as far as the
             * link is concerned, and counting it keeps the loss figure honest
             * about a radio that is failing to transmit. */
            rftest_note_sent(&g_rft);
            continue;
        }
        rftest_note_sent(&g_rft);

        uint32_t waited = 0;
        while (!g_rft_got && waited < RFTEST_TIMEOUT_MS) {
            rx_window(RF_POLL_MS);
            waited += RF_POLL_MS;
        }
        if (g_rft_got) {
            uint32_t rtt = (uint32_t)(esp_timer_get_time() / 1000) - t0;
            rftest_note_echo(&g_rft, rtt, g_radio.last_rssi_dbm, g_radio.last_snr_x4,
                             g_rft_rssi_there, g_rft_snr_there);
            printf("  %3u  %4lu ms  us->them %4d dBm  them->us %4d dBm\n",
                   (unsigned)i, (unsigned long)rtt, g_rft_rssi_there, g_radio.last_rssi_dbm);
        } else {
            printf("  %3u  lost\n", (unsigned)i);
        }
    }

    g_rft_active = false;

    char report[512];
    rftest_format(&g_rft, report, sizeof(report));
    printf("%s\n", report);
    return true;
}

/* -- sensing ---------------------------------------------------------------- */

static void maybe_read_gnss(bool force, uint8_t *gnss_status, bool *fix_valid)
{
    *gnss_status = GNSS_STATUS(GNSS_NO_FIX, 0);
    *fix_valid = false;

    if (!g_have_gnss || !(g_cfg.cfg.flags & CFG_FLAG_GNSS_ENABLED)) return;

    /*
     * Not "|| !g_rtc.time_valid" any more. Using the receiver as a clock
     * source sounds free and is not: indoors or under cover it finds nothing,
     * so a node that has not been synced burns 45 s and ~45 mA every single
     * cycle for a fix that will not come, and spends the rest of the cycle
     * too busy to hear the TIME_SYNC that would have fixed it. The clock
     * comes from the gateway; the GNSS keeps its own schedule.
     */
    bool due = force || (g_rtc.cycles % GNSS_EVERY_N_CYCLES) == 0;
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

    /* Nothing to do for the clock: the RTC timer runs through deep sleep and
     * `time()` reads it on the other side. Advancing an anchor by the sleep
     * we *asked* for -- which is what used to happen here -- credited the
     * full interval even when EXT1 cut the sleep short, so every impact wake
     * pushed the node further into the future. See the note above node_now().
     */

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

/*
 * What the node's pixel says, and it says one thing: can this node reach the
 * field? Tilt and battery are not in here on purpose. They are reported over
 * the mesh and shown on a dashboard that can put a number next to them, and a
 * light that tries to say six things says none of them clearly. What a light
 * is uniquely good at is the failure that stops the mesh reporting at all --
 * which is exactly the failure the dashboard cannot tell you about, because a
 * node that cannot transmit looks identical to a node nobody has installed.
 */
static statusled_code_t led_code(void)
{
    uint32_t now_ms = (uint32_t)(esp_timer_get_time() / 1000);
    statusled_node_input_t in = {
        .radio_up = g_have_radio,
        .tx_ok    = g_tx_ok,
        .uptime_s = now_ms / 1000,
        /* UINT32_MAX until the first frame, so "never heard anything" and
         * "heard something a moment ago" cannot be confused by arithmetic. */
        .heard_s  = g_last_rx_ms ? (now_ms - g_last_rx_ms) / 1000 : UINT32_MAX,
    };
    return statusled_evaluate_node(&in);
}

static bool gnss_raw_test(uint32_t seconds)
{
    if (!g_have_gnss) return false;
    /* Deliberately ignores CFG_FLAG_GNSS_ENABLED: somebody typing this is
     * diagnosing the receiver, and refusing because the feature flag is off
     * would answer a question they did not ask. */
    gnss_raw_dump(&g_gnss, seconds, NULL);
    return true;
}

static void init_status_led(void)
{
    /*
     * Say so either way. A silent "off" is indistinguishable from a broken
     * driver or a wrong pin, and the whole point of the indicator is to make
     * a failure legible without a laptop -- an indicator whose own absence is
     * unexplained fails at that before it starts.
     */
    if (!(g_cfg.cfg.flags & CFG_FLAG_LED_ENABLED)) {
        /*
         * On by default, so reaching here means somebody cleared bit 5 -- or,
         * far more likely, this board's config was saved before the flag
         * existed and NVS is faithfully restoring the old value. Either way a
         * silent dark pixel is indistinguishable from a broken driver, so say
         * which it is and how to change it.
         */
        ESP_LOGW(TAG, "status LED off (flags 0x%02X, bit 5 clear -- default is on; "
                      "a config saved before this flag existed will not have it). "
                      "To light it: `set flags 0x%02X` / `save` / `reboot`",
                 g_cfg.cfg.flags,
                 (unsigned)(g_cfg.cfg.flags | CFG_FLAG_LED_ENABLED));
        return;
    }

    /*
     * One thing a passer-by will otherwise misread, so the log says it: on a
     * deep-sleeping node the pixel is only alive during the wake window --
     * roughly two seconds a minute -- because the LED task dies with the rest
     * of the chip. A node that looks dark for fifty-eight seconds out of
     * sixty is working exactly as designed, not broken.
     */
    if (g_cfg.cfg.flags & CFG_FLAG_DEEP_SLEEP)
        ESP_LOGI(TAG, "status LED: alive only during the ~2 s wake window each "
                      "cycle, since deep sleep stops the chip. Dark between "
                      "cycles is normal");

    statusled_set_order(g_cfg.led_order_rgb ? STATUSLED_ORDER_RGB
                                            : STATUSLED_ORDER_GRB);
    statusled_start_code(g_cfg.led_gpio ? (gpio_num_t)g_cfg.led_gpio : PIN_RGB_LED,
                         led_code);
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

    /* After the radio, because the radio is what it reports on, and before the
     * console so a board that never reaches the prompt still says why. */
    init_status_led();

    if (cold_boot) {
        const nodecfg_hooks_t hooks = { .rftest = rf_run_test,
                                        .gnsstest = gnss_raw_test };
        nodecfg_cli_start(&g_cfg, &hooks);
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
         * A node without a clock keeps reporting. It used to stop and hunt
         * for a TIME_SYNC instead, and that was wrong in both directions.
         *
         * It assumed the downlink works. If it does not -- a one-way link,
         * which is a common and perfectly ordinary RF failure -- the node
         * never gets a clock, so it never sleeps, never aligns to a slot, and
         * hunts forever for a frame that is not coming. It also forced a GNSS
         * read every cycle looking for time, which costs 45 s of a 75 s cycle
         * and leaves it listening even less. A node stuck in that loop
         * produces nothing and flattens its battery doing it.
         *
         * And it was not necessary. The gateway has NTP and stamps whatever
         * it hears; a frame carrying epoch 0 says "I do not know the time"
         * and the backend substitutes arrival time. So an unsynchronised node
         * is worth strictly more reporting than sulking: the measurement is
         * the valuable part, and its timestamp is only a second or two of
         * airtime away from correct.
         *
         * What is genuinely lost without a clock is slot alignment -- the
         * whole field waking in the same window -- and node-side rate
         * thresholds, which need to divide by a real interval. Both come back
         * the moment a TIME_SYNC does arrive.
         */
        if (!g_rtc.time_valid)
            ESP_LOGW(TAG, "no clock: free-running at %u s and stamping frames "
                          "epoch 0. The gateway will timestamp them on arrival",
                     g_cfg.cfg.sample_interval_s);

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
