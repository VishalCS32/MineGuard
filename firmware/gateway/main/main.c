/*
 * SUBSIDENCE-NET gateway -- ESP32-S3 + E220 + SIM800L + microSD.
 *
 * The same board as a node, with different modules on the same headers and a
 * different value in NVS. See firmware/common/board_pins.h.
 *
 * The boundary between a radio network and a data pipeline, and the one device
 * in the field with a real power budget. Everything here is ordered by what
 * must survive what:
 *
 *   1. RECEIVE AND WRITE DOWN.       Every frame is spooled before anything
 *      else is attempted with it. A failed POST must never cost a measurement.
 *   2. DECIDE LOCALLY.               A critical event goes to SMS from here,
 *      with no server in the path. This is the 3 a.m. path.
 *   3. UPLINK WHEN POSSIBLE.         Batches of up to 64 frames, over MQTT if a
 *      broker is configured and HTTP otherwise, retried until they land.
 *   4. CARRY THE CLOCK AND CONTROL BACK DOWN. TIME_SYNC to the whole field,
 *      CONFIG_SET to individual nodes.
 *
 * The ordering is the design. A gateway that posts before it spools loses data
 * when the WAN drops; one that waits for the backend before deciding on an
 * event is an alerting system with a single point of failure in a data centre.
 *
 * ON DOWNLINK TIMING. Nodes deep sleep and are awake for about two seconds a
 * minute, so a downlink transmitted at an arbitrary moment reaches nobody. The
 * gateway holds pending frames and sends each one the instant it hears from
 * that node -- a frame just received is proof the sender is awake right now.
 * That is worth more than any wake-on-radio scheme: it costs no extra airtime
 * and it cannot miss the window.
 */
#define BOARD_GATEWAY

#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sys/time.h>
#include <time.h>

#include "battery.h"
#include "board_pins.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include "fieldview.h"
#include "gwrules.h"
#include "llcc68.h"
#include "meshnet.h"
#include "nodecfg.h"
#include "sim800l.h"
#include "spool.h"
#include "statusled.h"
#include "subnet_proto.h"
#include "report.h"
#include "uplink.h"
#include "webui.h"

static const char *TAG = "gateway";

/* -- tuning ---------------------------------------------------------------- */

#define UPLINK_INTERVAL_MS      5000     /* how often a batch is attempted     */
#define TIME_SYNC_INTERVAL_S    600      /* nodes drift ~20 ppm between these  */
#define CONFIG_POLL_INTERVAL_MS 3000     /* one node per tick, HTTP only       */
/* How often the decoded realtime document goes to the push endpoint, when one
 * is configured. Ten seconds is well inside a node's 60 s cadence, so nothing
 * is ever more than one cycle stale, and it is far cheaper than pushing on
 * every frame from a 21-node field. */
#define PUSH_INTERVAL_MS        10000
#define DOWNLINK_TTL_S          1800     /* give up on an unreachable node     */
#define MAX_PENDING_DOWNLINKS   8
#define SMS_QUEUE_DEPTH         8

/* -- state ------------------------------------------------------------------ */

typedef struct {
    uint16_t dst;
    uint8_t  frame[SUBNET_MAX_FRAME];
    uint8_t  len;
    uint32_t queued_epoch;
    uint8_t  attempts;
    bool     used;
} pending_t;

static nodecfg_t  g_cfg;
static llcc68_t   g_radio;
static meshnet_t  g_mesh;
static gwrules_t  g_rules;
static sim800l_t  g_modem;
static bool       g_have_radio, g_have_modem;

static pending_t  g_pending[MAX_PENDING_DOWNLINKS];

static uint32_t   g_last_frame_ms;       /* any node, any type: the field's pulse */

static SemaphoreHandle_t g_radio_lock;   /* the RX task and the downlink share it */
static QueueHandle_t     g_sms_queue;    /* char[GWRULES_SMS_LEN]                 */

static uint32_t now_epoch(void)
{
    /* Before NTP the gateway has no idea what time it is, and a frame stamped
     * with 1970 would poison every rate the backend derives. Zero is the honest
     * answer and the ingest path treats it as such. */
    if (!uplink_time_valid()) return 0;
    return (uint32_t)time(NULL);
}

/* -- radio ------------------------------------------------------------------ */

static bool radio_send(const uint8_t *frame, size_t len)
{
    if (!g_have_radio) return false;
    xSemaphoreTake(g_radio_lock, portMAX_DELAY);

    bool busy = false;
    for (int i = 0; i < 4; i++) {
        if (llcc68_cad(&g_radio, &busy, 200) != ESP_OK) break;
        if (!busy) break;
        vTaskDelay(pdMS_TO_TICKS(10 + esp_random() % 100));
    }
    esp_err_t err = llcc68_send(&g_radio, frame, (uint8_t)len, 4000);
    llcc68_start_rx(&g_radio);

    xSemaphoreGive(g_radio_lock);
    return err == ESP_OK;
}

/* -- downlink queue ---------------------------------------------------------- */

static void downlink_enqueue(const uint8_t *frame, size_t len)
{
    subnet_frame_t f;
    if (subnet_frame_parse(frame, len, &f) != SUBNET_OK) return;

    pending_t *slot = NULL;
    for (int i = 0; i < MAX_PENDING_DOWNLINKS; i++) {
        /* One pending config per node: a newer one supersedes an older one
         * outright, because sending both would have the node apply and ACK a
         * config the dashboard has already replaced. */
        if (g_pending[i].used && g_pending[i].dst == f.dst) { slot = &g_pending[i]; break; }
        if (!g_pending[i].used && !slot) slot = &g_pending[i];
    }
    if (!slot) {
        ESP_LOGW(TAG, "downlink queue full; dropping a config for 0x%04X", f.dst);
        return;
    }

    memcpy(slot->frame, frame, len);
    slot->len = (uint8_t)len;
    slot->dst = f.dst;
    slot->queued_epoch = now_epoch();
    slot->attempts = 0;
    slot->used = true;

    ESP_LOGI(TAG, "downlink held for 0x%04X (%u B); it goes out the moment that "
                  "node is next heard from", f.dst, (unsigned)len);

    /* A broadcast downlink -- TIME_SYNC -- has no single node to wait for. */
    if (f.dst == ADDR_BROADCAST) {
        radio_send(slot->frame, slot->len);
        slot->used = false;
    }
}

/* The node is demonstrably awake: it just transmitted. */
static void downlink_flush_for(uint16_t addr)
{
    uint32_t now = now_epoch();
    for (int i = 0; i < MAX_PENDING_DOWNLINKS; i++) {
        pending_t *p = &g_pending[i];
        if (!p->used || p->dst != addr) continue;

        if (now && p->queued_epoch && (now - p->queued_epoch) > DOWNLINK_TTL_S) {
            ESP_LOGW(TAG, "downlink for 0x%04X expired unacknowledged after %d s",
                     addr, DOWNLINK_TTL_S);
            p->used = false;
            continue;
        }
        /* Straight after the node's own transmission, while it is still in its
         * receive window. */
        vTaskDelay(pdMS_TO_TICKS(60));
        if (radio_send(p->frame, p->len)) {
            p->attempts++;
            ESP_LOGI(TAG, "sent config to 0x%04X (attempt %u); it stays queued "
                          "until the ACK arrives", addr, p->attempts);
        }
    }
}

static void downlink_ack_seen(uint16_t src)
{
    for (int i = 0; i < MAX_PENDING_DOWNLINKS; i++)
        if (g_pending[i].used && g_pending[i].dst == src) g_pending[i].used = false;
}

/* -- frame handling ---------------------------------------------------------- */

static void queue_sms(const char *text)
{
    char msg[GWRULES_SMS_LEN];
    strncpy(msg, text, sizeof(msg) - 1);
    msg[sizeof(msg) - 1] = '\0';
    if (xQueueSend(g_sms_queue, msg, 0) != pdTRUE)
        ESP_LOGW(TAG, "SMS queue full; dropped: %s", msg);
}

static void handle_frame(uint8_t *buf, uint16_t len)
{
    subnet_frame_t f;
    subnet_err_t err = subnet_frame_parse(buf, len, &f);
    if (err != SUBNET_OK) {
        /* Corrupt frames are expected on a real link, not exceptional. Counted
         * so the delivery figure on the dashboard stays honest. */
        g_mesh.dropped_bad++;
        return;
    }

    uint8_t snr_field = (uint8_t)((g_radio.last_snr_x4 + 80) < 0 ? 0 :
                                  (g_radio.last_snr_x4 + 80) > 255 ? 255 :
                                  (g_radio.last_snr_x4 + 80));
    uint32_t ms = (uint32_t)(esp_timer_get_time() / 1000);
    meshnet_note_neighbor(&g_mesh, f.src, g_radio.last_rssi_dbm, snr_field, ms);

    meshnet_action_t action = meshnet_on_rx(&g_mesh, &f, ms);
    if (action == MESHNET_DROP) return;   /* the same frame down another path */

    /* The on-site UI's view of the field, and the list the HTTP downlink poller
     * walks. Both want the same thing: every node this gateway has heard. */
    fieldview_heard(f.src, g_radio.last_rssi_dbm, snr_field, f.hops, ms);
    g_last_frame_ms = ms;
    statusled_note_frame();     /* one flick of the LED per frame received */

    /* Everything gets written down, whatever it is and whatever else happens to
     * it: the backend is the component that knows how to interpret frames, and
     * the gateway's job is to make sure it eventually gets them all. */
    spool_push(buf, (uint8_t)len);

    uint32_t now = now_epoch();
    char sms[GWRULES_SMS_LEN];

    switch (f.type) {
    case MSG_EVENT: {
        evt_t e;
        memcpy(&e, f.payload, sizeof(e));
        fieldview_event(f.src, &e);
        ESP_LOGW(TAG, "EVENT from 0x%04X: code 0x%02X severity %u value %ld",
                 f.src, e.event_code, e.severity, (long)e.value);
        /* The local path. No server involved, and deliberately so. */
        if (gwrules_on_event(&g_rules, f.src, &e, now ? now : (uint32_t)time(NULL),
                             sms, sizeof(sms)))
            queue_sms(sms);
        break;
    }
    case MSG_TELEMETRY: {
        tlm_t t;
        memcpy(&t, f.payload, sizeof(t));
        fieldview_telemetry(f.src, &t);
        if (gwrules_on_telemetry(&g_rules, f.src, &t, now ? now : (uint32_t)time(NULL),
                                 sms, sizeof(sms)))
            queue_sms(sms);
        break;
    }
    case MSG_CONFIG_ACK:
        /* The loop closes here: the node is running the config, so stop
         * retransmitting it. The backend learns the same thing from the spooled
         * frame when the uplink next succeeds. */
        downlink_ack_seen(f.src);
        break;
    default:
        break;
    }

    /* Whatever it was, this node is awake right now. */
    downlink_flush_for(f.src);

    if (action == MESHNET_RELAY || action == MESHNET_CONSUME_AND_RELAY) {
        /* The gateway relays too. It is usually the best-sited radio on the
         * field and it is never asleep, so refusing to forward would be
         * throwing away the strongest link in the mesh. */
        if (meshnet_prepare_relay(buf, len, &f)) radio_send(buf, len);
    }
}

/* -- tasks -------------------------------------------------------------------- */

static void radio_task(void *arg)
{
    (void)arg;
    llcc68_start_rx(&g_radio);

    for (;;) {
        uint8_t buf[SUBNET_MAX_FRAME];
        uint8_t len = 0;

        xSemaphoreTake(g_radio_lock, portMAX_DELAY);
        esp_err_t err = llcc68_poll_rx(&g_radio, buf, sizeof(buf), &len);
        xSemaphoreGive(g_radio_lock);

        if (err == ESP_OK && len) handle_frame(buf, len);
        else vTaskDelay(pdMS_TO_TICKS(5));
    }
}

static void broadcast_time_sync(void)
{
    if (!uplink_time_valid()) return;

    struct timeval tv;
    gettimeofday(&tv, NULL);
    timesync_t ts = {
        .t_epoch = (uint32_t)tv.tv_sec,
        .t_millis = (uint16_t)(tv.tv_usec / 1000),
    };
    uint8_t frame[SUBNET_MAX_FRAME];
    size_t n = subnet_frame_build(frame, sizeof(frame), MSG_TIME_SYNC,
                                  ADDR_GATEWAY, ADDR_BROADCAST,
                                  meshnet_next_seq(&g_mesh), MESH_DEFAULT_TTL, 0,
                                  &ts, sizeof(ts));
    if (n && radio_send(frame, n))
        ESP_LOGI(TAG, "TIME_SYNC broadcast: %lu", (unsigned long)ts.t_epoch);
}

static void uplink_task(void *arg)
{
    (void)arg;
    int64_t next_sync_us = 0, next_push_us = 0;
    int poll_cursor = 0;

    for (;;) {
        spool_batch_t batch;
        if (spool_peek(&batch) > 0) {
            if (uplink_send_batch(&batch)) {
                spool_consume(batch.count);
                gwrules_note_uplink_ok(&g_rules, (uint32_t)time(NULL));
            } else {
                /* Nothing is consumed on failure; the frames stay spooled and
                 * the next attempt starts with the same ones. */
                ESP_LOGW(TAG, "uplink failed; %u frames waiting",
                         (unsigned)spool_depth());
            }
        }

        /*
         * The realtime feed. Separate from the ingest path above and
         * deliberately so: that one carries raw frames to the system of record
         * and is retried until they land, this one is a decoded convenience
         * document that is allowed to fail. A push that could block or delay
         * the frame path would be trading a warning for a dashboard.
         */
        if (g_cfg.push_url[0] && esp_timer_get_time() >= next_push_us) {
            char *doc = report_push_document();
            if (doc) {
                uplink_push_json(doc);
                free(doc);
            }
            next_push_us = esp_timer_get_time() + (int64_t)PUSH_INTERVAL_MS * 1000;
        }

        /* The field's clock, sent on a schedule rather than on demand: a node
         * that missed the last one gets the next without having to ask. */
        if (esp_timer_get_time() >= next_sync_us) {
            broadcast_time_sync();
            next_sync_us = esp_timer_get_time() + (int64_t)TIME_SYNC_INTERVAL_S * 1000000;
        }

        /* With no broker there is nobody to push a config down, so the gateway
         * asks -- one node per pass, round robin. Twenty-one nodes cost one
         * small request every few seconds rather than twenty-one at once. */
        int known = fieldview_count();
        if (known > 0) {
            fieldview_node_t n;
            poll_cursor = (poll_cursor + 1) % known;
            if (fieldview_get(poll_cursor, &n)) uplink_poll_config(n.addr);
        }

        vTaskDelay(pdMS_TO_TICKS(UPLINK_INTERVAL_MS));
    }
}

static void sms_task(void *arg)
{
    (void)arg;
    char msg[GWRULES_SMS_LEN];

    for (;;) {
        if (xQueueReceive(g_sms_queue, msg, portMAX_DELAY) != pdTRUE) continue;

        if (!g_have_modem || !g_cfg.sms_recipients[0]) {
            ESP_LOGE(TAG, "SMS not sent (%s): %s",
                     g_have_modem ? "no recipients configured" : "no modem",
                     msg);
            continue;
        }
        int sent = sim800l_send_sms(&g_modem, g_cfg.sms_recipients, msg);
        ESP_LOGW(TAG, "SMS to %d recipient(s): %s", sent, msg);
    }
}

/* -- the web UI's view of ourselves ------------------------------------------- */

static void gateway_status(gw_status_t *out)
{
    memset(out, 0, sizeof(*out));
    out->rx_total   = g_mesh.rx_total;
    out->rx_dup     = g_mesh.rx_dup;
    out->rx_bad     = g_mesh.dropped_bad;
    out->relayed    = g_mesh.relayed;

    out->spool_depth = spool_depth();
    out->spool_shed  = spool_shed();
    out->spool_sd    = spool_using_sd();

    uplink_stats(&out->posted, &out->post_failures, &out->downlinks);
    out->link_down = gwrules_link_is_down(&g_rules, (uint32_t)time(NULL));

    out->sms_sent       = g_rules.sent;
    out->sms_suppressed = g_rules.suppressed;
    out->modem_ready    = g_have_modem;
    out->modem_registered = g_modem.registered;
    out->modem_csq      = g_modem.last_csq;

    out->radio_up = g_have_radio;
    out->tx_count = g_radio.tx_count;
    out->rx_count = g_radio.rx_count;
    out->crc_err  = g_radio.crc_err_count;

    out->vbat_mv = battery_read_mv();
}

static void led_source(statusled_input_t *out)
{
    memset(out, 0, sizeof(*out));
    uint32_t now_ms = (uint32_t)(esp_timer_get_time() / 1000);

    out->radio_up         = g_have_radio;
    out->wifi_up          = uplink_wifi_up();
    out->backend_ok       = !gwrules_link_is_down(&g_rules, (uint32_t)time(NULL));
    out->modem_ready      = g_have_modem;
    out->modem_registered = g_modem.registered;
    out->spool_depth      = (uint32_t)spool_depth();
    out->uptime_s         = now_ms / 1000;
    /* UINT32_MAX until the first frame, so "never heard anything" and "heard
     * something a moment ago" cannot be confused by the arithmetic. */
    out->quiet_s = g_last_frame_ms ? (now_ms - g_last_frame_ms) / 1000 : UINT32_MAX;
}

/* The test button on the page. It goes through the same queue and the same
 * modem as a real alert, because a test that takes a different path proves
 * nothing about the path that matters. */
static int webui_test_sms(const char *text)
{
    if (!g_have_modem || !g_cfg.sms_recipients[0]) return 0;
    return sim800l_send_sms(&g_modem, g_cfg.sms_recipients, text);
}

/* -- bring-up ----------------------------------------------------------------- */

static void init_radio(void)
{
    llcc68_cfg_t rc = llcc68_default_cfg();
    rc.host  = SPI2_HOST;   /* GPIO11-13 are this bus's IOMUX pins on the S3 */
    rc.sck   = PIN_LORA_SCK;   rc.miso = PIN_LORA_MISO;
    rc.mosi  = PIN_LORA_MOSI;  rc.nss  = PIN_LORA_NSS;
    rc.busy  = PIN_LORA_BUSY;  rc.dio1 = PIN_LORA_DIO1;
    rc.reset = PIN_LORA_RST;
    rc.tx_dbm = 22;

    g_have_radio = (llcc68_init(&g_radio, &rc) == ESP_OK);
    if (!g_have_radio)
        ESP_LOGE(TAG, "radio did not come up -- the gateway can still uplink "
                      "whatever is already spooled, and nothing else");
}

static void init_modem(void)
{
    sim800l_cfg_t mc = {
        .uart = UART_NUM_1, .tx = PIN_SIM_TX, .rx = PIN_SIM_RX,
        .pwrkey = PIN_SIM_PWRKEY, .status = PIN_SIM_STATUS, .baud = 9600,
    };
    g_have_modem = (sim800l_init(&g_modem, &mc) == ESP_OK);
    if (!g_have_modem)
        ESP_LOGE(TAG, "no modem: the offline alerting path is DOWN. "
                      "Alerts now depend entirely on the backend being reachable.");
}

void app_main(void)
{
    nodecfg_load(&g_cfg);
    if (g_cfg.role != NODE_ROLE_GATEWAY)
        ESP_LOGW(TAG, "this board is provisioned as a node; run `set role gateway`, "
                      "`set addr 0x0001`, `save`");

    g_radio_lock = xSemaphoreCreateMutex();
    g_sms_queue  = xQueueCreate(SMS_QUEUE_DEPTH, GWRULES_SMS_LEN);

    /* The gateway is a mesh participant like any other, at the reserved
     * address, and it relays: it is never asleep and usually the best-sited
     * antenna on the site. */
    meshnet_init(&g_mesh, g_cfg.addr ? g_cfg.addr : ADDR_GATEWAY, true);

    gwrules_cfg_t rules = gwrules_default_cfg();
    gwrules_init(&g_rules, &rules);

    fieldview_init();
    init_radio();
    spool_init();
    init_modem();

    battery_cfg_t bat = {
        .adc_gpio = PIN_VBAT_ADC,
        .enable_gpio = GPIO_NUM_NC,   /* the gateway's rail is always sensed */
        .divider_x100 = VBAT_DIVIDER_X100,
    };
    battery_init(&bat);

    uplink_start(&g_cfg, downlink_enqueue);

    /* The indicator, before the tasks: it is the only thing that reports a
     * failure to somebody who is standing next to the box rather than looking
     * at a screen, so it should be running before anything can fail. */
    statusled_start(PIN_STATUS_LED, false, led_source);

    /* The on-site UI. Started last, so by the time a phone can reach it every
     * counter it displays is real. */
    report_init(&g_cfg, gateway_status);
    const webui_hooks_t hooks = { .test_sms = webui_test_sms };
    webui_start(&g_cfg, &hooks);

    nodecfg_cli_start(&g_cfg);
    nodecfg_print(&g_cfg);

    /* Priorities in the order things must not be missed: a frame arrives once
     * and is gone; an uplink and an SMS can both wait a second. */
    xTaskCreate(radio_task,  "radio",  4096, NULL, 6, NULL);
    xTaskCreate(uplink_task, "uplink", 8192, NULL, 4, NULL);
    xTaskCreate(sms_task,    "sms",    4096, NULL, 3, NULL);

    uplink_net_t net;
    uplink_netinfo(&net);
    ESP_LOGI(TAG, "gateway %s up: site=%s api=%s transport=%s spool=%s",
             g_cfg.gateway_id, g_cfg.site_slug, g_cfg.api_url,
             g_cfg.mqtt_host[0] ? "mqtt+http" : "http",
             spool_using_sd() ? "microSD" : "RAM (lost on reboot)");
    ESP_LOGI(TAG, "on-site UI: join \"%s\" and open http://%s",
             net.ap_ssid, net.ap_ip);
    if (g_cfg.push_url[0])
        ESP_LOGI(TAG, "realtime push: every %d s to %s",
                 PUSH_INTERVAL_MS / 1000, g_cfg.push_url);

    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(60000));
        uint32_t posted = 0, failures = 0, downlinks = 0;
        uplink_stats(&posted, &failures, &downlinks);
        ESP_LOGI(TAG, "rx %lu (dup %lu, bad %lu, relayed %lu) | spooled %u "
                      "(shed %u) | posted %lu, failed %lu | downlinks %lu | "
                      "sms sent %lu suppressed %lu | wifi %s",
                 (unsigned long)g_mesh.rx_total, (unsigned long)g_mesh.rx_dup,
                 (unsigned long)g_mesh.dropped_bad, (unsigned long)g_mesh.relayed,
                 (unsigned)spool_depth(), (unsigned)spool_shed(),
                 (unsigned long)posted, (unsigned long)failures,
                 (unsigned long)downlinks,
                 (unsigned long)g_rules.sent, (unsigned long)g_rules.suppressed,
                 uplink_wifi_up() ? "up" : "down");
    }
}
