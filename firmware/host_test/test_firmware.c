/*
 * Host tests for the firmware's portable core.
 *
 * The radio drivers need hardware. The frame codec and the mesh logic do not,
 * and they are where the bugs that cost a field trip live -- a CRC computed over
 * the wrong span, a flood that never terminates, a relay that forwards its own
 * traffic back into the network. All of that is decided by pure functions, so
 * all of it is tested here with cc and no ESP32 in sight.
 *
 * Build and run:  firmware/host_test/run.sh
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "gnss_nmea.h"
#include "gwrules.h"
#include "llcc68_limits.h"
#include "meshnet.h"
#include "nodelogic.h"
#include "statusled_pattern.h"
#include "subnet_proto.h"

static int checks = 0, failures = 0;
static const char *current;

#define CHECK(cond, msg) do {                                                  \
    checks++;                                                                  \
    if (!(cond)) { failures++;                                                 \
        printf("  FAIL  %s: %s\n         (%s:%d)\n", current, msg,             \
               __FILE__, __LINE__); }                                          \
} while (0)

#define TEST(name) do { current = name; printf("  %s\n", name); } while (0)

/* ------------------------------------------------------------ frame codec */

static void test_roundtrip(void)
{
    TEST("telemetry round trip preserves every field");
    tlm_t t = {
        .t_epoch = 1767225600u, .pitch_mdeg = -1234, .roll_mdeg = 5678,
        .vib_rms_mg = 412, .vib_peak_hz = 37, .temp_c_x100 = 2735,
        .n_samples = 32, .gnss_status = GNSS_STATUS(GNSS_FIX_3D, 9),
        .vbat_mv = 3987, .rssi = -87, .snr = 122,
        .flags = TLM_FLAG_RELAYED, .reserved = 0,
    };
    uint8_t buf[SUBNET_MAX_FRAME];
    size_t n = subnet_frame_build(buf, sizeof(buf), MSG_TELEMETRY, 0x42,
                                  ADDR_GATEWAY, 0x1337, MESH_DEFAULT_TTL, 2,
                                  &t, sizeof(t));
    CHECK(n == 34, "a telemetry frame is 34 bytes -- the SF9 airtime budget");

    subnet_frame_t f;
    CHECK(subnet_frame_parse(buf, n, &f) == SUBNET_OK, "parses");
    CHECK(f.type == MSG_TELEMETRY && f.src == 0x42 && f.dst == ADDR_GATEWAY, "header");
    CHECK(f.seq == 0x1337 && f.ttl == MESH_DEFAULT_TTL && f.hops == 2, "routing fields");
    CHECK(memcmp(f.payload, &t, sizeof(t)) == 0, "payload survives byte for byte");
}

static void test_all_types_roundtrip(void)
{
    TEST("every message type round trips at its declared size");
    struct { uint8_t type; uint16_t len; } cases[] = {
        { MSG_TELEMETRY,  sizeof(tlm_t)      },
        { MSG_EVENT,      sizeof(evt_t)      },
        { MSG_CONFIG_SET, sizeof(cfg_t)      },
        { MSG_CONFIG_ACK, sizeof(cfg_ack_t)  },
        { MSG_TIME_SYNC,  sizeof(timesync_t) },
        { MSG_POSITION,   sizeof(pos_t)      },
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        uint8_t payload[MESH_MAX_PAYLOAD];
        for (uint16_t b = 0; b < cases[i].len; b++) payload[b] = (uint8_t)(b * 7 + 1);

        uint8_t buf[SUBNET_MAX_FRAME];
        size_t n = subnet_frame_build(buf, sizeof(buf), cases[i].type, 0x10,
                                      ADDR_GATEWAY, 1, 4, 0, payload, cases[i].len);
        CHECK(n == (size_t)MESH_HDR_LEN + cases[i].len, "length");
        CHECK(subnet_payload_len(cases[i].type) == cases[i].len, "declared size matches struct");

        subnet_frame_t f;
        CHECK(subnet_frame_parse(buf, n, &f) == SUBNET_OK, "parses");
        CHECK(memcmp(f.payload, payload, cases[i].len) == 0, "payload intact");
    }
}

static void test_corruption_is_caught(void)
{
    TEST("a corrupted frame is rejected, never misread");
    tlm_t t = { .t_epoch = 1767225600u, .pitch_mdeg = 100 };
    uint8_t buf[SUBNET_MAX_FRAME];
    size_t n = subnet_frame_build(buf, sizeof(buf), MSG_TELEMETRY, 0x10,
                                  ADDR_GATEWAY, 1, 4, 0, &t, sizeof(t));

    /* Every single-bit flip in the whole frame must be caught. This is the
     * property the radio actually depends on. */
    int missed = 0;
    for (size_t byte = 0; byte < n; byte++) {
        for (int bit = 0; bit < 8; bit++) {
            uint8_t copy[SUBNET_MAX_FRAME];
            memcpy(copy, buf, n);
            copy[byte] ^= (uint8_t)(1 << bit);
            if (subnet_frame_parse(copy, n, NULL) == SUBNET_OK) missed++;
        }
    }
    CHECK(missed == 0, "every single-bit flip in the frame is detected");

    uint8_t bad_magic[SUBNET_MAX_FRAME];
    memcpy(bad_magic, buf, n); bad_magic[0] = 0x00;
    CHECK(subnet_frame_parse(bad_magic, n, NULL) == SUBNET_ERR_MAGIC, "bad magic");

    uint8_t bad_ver[SUBNET_MAX_FRAME];
    memcpy(bad_ver, buf, n); bad_ver[1] = VER_TYPE(0xF, MSG_TELEMETRY);
    CHECK(subnet_frame_parse(bad_ver, n, NULL) == SUBNET_ERR_VERSION, "bad version");

    CHECK(subnet_frame_parse(buf, MESH_HDR_LEN - 1, NULL) == SUBNET_ERR_SHORT, "runt");
}

static void test_wrong_length_for_type_is_rejected(void)
{
    TEST("a payload of the wrong size for its type is refused");
    /* Otherwise it would be cast onto the wrong struct and read as plausible
     * garbage -- far more dangerous than a frame that is simply dropped. */
    uint8_t payload[sizeof(tlm_t) - 1] = {0};
    uint8_t buf[SUBNET_MAX_FRAME];
    size_t n = subnet_frame_build(buf, sizeof(buf), MSG_TELEMETRY, 0x10,
                                  ADDR_GATEWAY, 1, 4, 0, payload, sizeof(payload));
    CHECK(subnet_frame_parse(buf, n, NULL) == SUBNET_ERR_LENGTH, "short telemetry rejected");
}

static void test_oversize_payload_refused(void)
{
    TEST("a payload beyond the radio budget is refused at build time");
    uint8_t big[MESH_MAX_PAYLOAD + 1] = {0};
    uint8_t buf[SUBNET_MAX_FRAME];
    CHECK(subnet_frame_build(buf, sizeof(buf), MSG_TELEMETRY, 1, 2, 3, 4, 0,
                             big, sizeof(big)) == 0, "refused");
}

static void test_neighbor_variable_length(void)
{
    TEST("neighbour reports validate their own variable length");
    uint8_t payload[MESH_MAX_PAYLOAD];
    neigh_hdr_t h = { .t_epoch = 1767225600u, .count = 3 };
    memcpy(payload, &h, sizeof(h));
    for (int i = 0; i < 3; i++) {
        neigh_entry_t e = { .addr = (uint16_t)(0x20 + i), .rssi = (int8_t)(-70 - i), .snr = 100 };
        memcpy(payload + sizeof(h) + i * sizeof(e), &e, sizeof(e));
    }
    uint16_t len = sizeof(h) + 3 * sizeof(neigh_entry_t);

    uint8_t buf[SUBNET_MAX_FRAME];
    size_t n = subnet_frame_build(buf, sizeof(buf), MSG_NEIGHBOR, 0x10,
                                  ADDR_GATEWAY, 1, 4, 0, payload, len);
    CHECK(subnet_frame_parse(buf, n, NULL) == SUBNET_OK, "well-formed report parses");

    /* A count that disagrees with the byte length must not be trusted: it would
     * walk the reader off the end of the buffer. */
    ((neigh_hdr_t *)(buf + MESH_HDR_LEN))->count = 7;
    subnet_frame_rehop(buf, n, 4, 0);
    CHECK(subnet_frame_parse(buf, n, NULL) == SUBNET_ERR_LENGTH, "lying count rejected");

    ((neigh_hdr_t *)(buf + MESH_HDR_LEN))->count = 200;
    subnet_frame_rehop(buf, n, 4, 0);
    CHECK(subnet_frame_parse(buf, n, NULL) == SUBNET_ERR_LENGTH, "absurd count rejected");
}

static void test_rehop_keeps_the_frame_valid(void)
{
    TEST("re-hopping a frame repairs its CRC");
    tlm_t t = { .t_epoch = 1767225600u };
    uint8_t buf[SUBNET_MAX_FRAME];
    size_t n = subnet_frame_build(buf, sizeof(buf), MSG_TELEMETRY, 0x10,
                                  ADDR_GATEWAY, 1, 4, 0, &t, sizeof(t));
    subnet_frame_rehop(buf, n, 3, 1);

    subnet_frame_t f;
    CHECK(subnet_frame_parse(buf, n, &f) == SUBNET_OK, "still valid after rewrite");
    CHECK(f.ttl == 3 && f.hops == 1, "ttl and hops updated");
    CHECK(f.src == 0x10 && f.seq == 1, "nothing else disturbed");
}

static void test_config_hash(void)
{
    TEST("config hash covers the fields and excludes itself");
    cfg_t c = {
        .cfg_version = 1, .sample_interval_s = 60, .wor_period_ms = 2000,
        .tx_power_dbm = 22, .tilt_alert_mdeg = 2000, .vib_alert_mg = 500,
        .tilt_rate_alert_mdeg_h = 150, .tilt_offset_pitch = 0,
        .tilt_offset_roll = 0, .flags = 0x0F, .cfg_hash = 0,
    };
    c.cfg_hash = subnet_cfg_hash(&c);
    CHECK(subnet_cfg_valid(&c), "a freshly hashed config validates");

    uint16_t before = c.cfg_hash;
    c.cfg_hash = 0xDEAD;
    CHECK(subnet_cfg_hash(&c) == before, "the hash field is not itself hashed");
    CHECK(!subnet_cfg_valid(&c), "a tampered hash is caught");

    c.cfg_hash = before;
    c.sample_interval_s = 61;
    CHECK(!subnet_cfg_valid(&c), "a changed field invalidates the hash");
}

/* ---------------------------------------------------------------- meshnet */

static uint8_t *make_frame(uint8_t *buf, size_t *len, uint16_t src, uint16_t dst,
                           uint16_t seq, uint8_t ttl, uint8_t hops)
{
    tlm_t t = { .t_epoch = 1767225600u };
    *len = subnet_frame_build(buf, SUBNET_MAX_FRAME, MSG_TELEMETRY,
                              src, dst, seq, ttl, hops, &t, sizeof(t));
    return buf;
}

static void test_flood_terminates(void)
{
    TEST("a flood is seen once and never echoes");
    meshnet_t m; meshnet_init(&m, 0x20, true);
    uint8_t buf[SUBNET_MAX_FRAME]; size_t len;
    make_frame(buf, &len, 0x10, ADDR_GATEWAY, 7, 4, 0);

    subnet_frame_t f;
    assert(subnet_frame_parse(buf, len, &f) == SUBNET_OK);

    CHECK(meshnet_on_rx(&m, &f, 1000) == MESHNET_RELAY, "first sighting is relayed");
    for (int i = 0; i < 20; i++)
        CHECK(meshnet_on_rx(&m, &f, 1000 + i) == MESHNET_DROP, "every repeat is dropped");
    CHECK(m.relayed == 1, "relayed exactly once");
    CHECK(m.rx_dup == 20, "the rest counted as duplicates");
}

static void test_own_frame_is_not_relayed(void)
{
    TEST("a node does not relay its own traffic back into the mesh");
    meshnet_t m; meshnet_init(&m, 0x10, true);
    uint8_t buf[SUBNET_MAX_FRAME]; size_t len;
    make_frame(buf, &len, 0x10, ADDR_GATEWAY, 3, 4, 1);

    subnet_frame_t f;
    assert(subnet_frame_parse(buf, len, &f) == SUBNET_OK);
    CHECK(meshnet_on_rx(&m, &f, 1000) == MESHNET_DROP, "dropped");
    CHECK(m.relayed == 0, "not relayed");
}

static void test_ttl_expiry(void)
{
    TEST("TTL bounds the flood");
    meshnet_t m; meshnet_init(&m, 0x20, true);
    uint8_t buf[SUBNET_MAX_FRAME]; size_t len;
    make_frame(buf, &len, 0x10, ADDR_GATEWAY, 9, 1, 3);

    subnet_frame_t f;
    assert(subnet_frame_parse(buf, len, &f) == SUBNET_OK);
    CHECK(meshnet_on_rx(&m, &f, 1000) == MESHNET_DROP, "ttl 1 is not forwarded");
    CHECK(m.dropped_ttl == 1, "counted");
    CHECK(!meshnet_prepare_relay(buf, (uint16_t)len, &f), "prepare_relay refuses too");
}

static void test_ttl_decrements_across_hops(void)
{
    TEST("ttl falls and hops rise, one per relay, until the flood dies");
    uint8_t buf[SUBNET_MAX_FRAME]; size_t len;
    make_frame(buf, &len, 0x10, ADDR_GATEWAY, 11, MESH_DEFAULT_TTL, 0);

    int hops_taken = 0;
    for (int hop = 0; hop < 10; hop++) {
        subnet_frame_t f;
        CHECK(subnet_frame_parse(buf, len, &f) == SUBNET_OK, "valid at every hop");
        /* A different relay each time, so nobody sees the frame twice. */
        meshnet_t m; meshnet_init(&m, (uint16_t)(0x20 + hop), true);
        if (meshnet_on_rx(&m, &f, 1000) != MESHNET_RELAY) break;
        if (!meshnet_prepare_relay(buf, (uint16_t)len, &f)) break;
        hops_taken++;
    }
    CHECK(hops_taken == MESH_DEFAULT_TTL - 1, "a TTL of 4 buys exactly 3 relays");

    subnet_frame_t f;
    assert(subnet_frame_parse(buf, len, &f) == SUBNET_OK);
    CHECK(f.hops == MESH_DEFAULT_TTL - 1, "hop count reports the path length");
}

static void test_addressed_frames(void)
{
    TEST("addressing decides consume, relay or both");
    meshnet_t m; meshnet_init(&m, 0x20, true);
    uint8_t buf[SUBNET_MAX_FRAME]; size_t len;
    subnet_frame_t f;

    make_frame(buf, &len, 0x01, 0x20, 1, 4, 0);
    assert(subnet_frame_parse(buf, len, &f) == SUBNET_OK);
    CHECK(meshnet_on_rx(&m, &f, 1000) == MESHNET_CONSUME, "addressed to us: consume");

    make_frame(buf, &len, 0x01, ADDR_BROADCAST, 2, 4, 0);
    assert(subnet_frame_parse(buf, len, &f) == SUBNET_OK);
    CHECK(meshnet_on_rx(&m, &f, 1000) == MESHNET_CONSUME_AND_RELAY,
          "broadcast: act on it and pass it on");
}

static void test_relay_disabled_node_still_receives_its_own_mail(void)
{
    TEST("a leaf node still receives frames addressed to it");
    meshnet_t m; meshnet_init(&m, 0x20, false);
    uint8_t buf[SUBNET_MAX_FRAME]; size_t len;
    subnet_frame_t f;

    make_frame(buf, &len, 0x01, 0x20, 1, 4, 0);
    assert(subnet_frame_parse(buf, len, &f) == SUBNET_OK);
    CHECK(meshnet_on_rx(&m, &f, 1000) == MESHNET_CONSUME, "consumed");

    make_frame(buf, &len, 0x10, ADDR_GATEWAY, 2, 4, 0);
    assert(subnet_frame_parse(buf, len, &f) == SUBNET_OK);
    CHECK(meshnet_on_rx(&m, &f, 1000) == MESHNET_DROP, "but forwards nothing");
}

static void test_seen_cache_ages_out(void)
{
    TEST("the de-duplication window ages out so sequence numbers can be reused");
    meshnet_t m; meshnet_init(&m, 0x20, true);
    CHECK(meshnet_mark_seen(&m, 0x10, 5, 1000), "first sighting");
    CHECK(!meshnet_mark_seen(&m, 0x10, 5, 1000), "immediate repeat suppressed");
    CHECK(meshnet_mark_seen(&m, 0x10, 5, 1000 + MESHNET_SEEN_TTL_MS + 1),
          "the same pair is fresh again long after the flood died");
}

static void test_seen_cache_survives_millis_wrap(void)
{
    TEST("de-duplication survives the millisecond counter wrapping");
    /* At 49.7 days uptime the tick counter wraps. Signed arithmetic here would
     * make every entry look impossibly old and let a flood restart. */
    meshnet_t m; meshnet_init(&m, 0x20, true);
    uint32_t near_wrap = 0xFFFFFF00u;
    CHECK(meshnet_mark_seen(&m, 0x10, 5, near_wrap), "seen just before the wrap");
    CHECK(!meshnet_mark_seen(&m, 0x10, 5, near_wrap + 100), "still suppressed after it");
}

static void test_seen_cache_holds_a_whole_field(void)
{
    TEST("the cache holds a frame from every node in a 21-node field at once");
    meshnet_t m; meshnet_init(&m, 0x01, true);
    for (uint16_t addr = 0x10; addr < 0x10 + 21; addr++)
        CHECK(meshnet_mark_seen(&m, addr, 1, 1000), "accepted");
    for (uint16_t addr = 0x10; addr < 0x10 + 21; addr++)
        CHECK(!meshnet_mark_seen(&m, addr, 1, 1100), "none evicted by the others");
}

static void test_neighbor_table_keeps_the_strongest(void)
{
    TEST("the neighbour table keeps the strongest links, not the most recent");
    meshnet_t m; meshnet_init(&m, 0x20, true);
    for (int i = 0; i < MESH_MAX_NEIGHBORS; i++)
        meshnet_note_neighbor(&m, (uint16_t)(0x30 + i), (int8_t)(-60 - i), 100, 1000);

    meshnet_note_neighbor(&m, 0x99, -120, 100, 2000);   /* weak, arrives later */
    bool found_weak = false;
    for (int i = 0; i < MESH_MAX_NEIGHBORS; i++)
        if (m.neighbors[i].addr == 0x99) found_weak = true;
    CHECK(!found_weak, "a weak latecomer does not evict a strong link");

    meshnet_note_neighbor(&m, 0x98, -40, 100, 2000);    /* strong */
    bool found_strong = false;
    for (int i = 0; i < MESH_MAX_NEIGHBORS; i++)
        if (m.neighbors[i].addr == 0x98) found_strong = true;
    CHECK(found_strong, "a strong latecomer does evict the weakest");
}

static void test_neighbor_updates_in_place(void)
{
    TEST("hearing a known neighbour again updates it rather than duplicating");
    meshnet_t m; meshnet_init(&m, 0x20, true);
    meshnet_note_neighbor(&m, 0x30, -80, 100, 1000);
    meshnet_note_neighbor(&m, 0x30, -55, 120, 2000);

    int seen = 0;
    for (int i = 0; i < MESH_MAX_NEIGHBORS; i++)
        if (m.neighbors[i].addr == 0x30) { seen++; CHECK(m.neighbors[i].rssi == -55, "updated"); }
    CHECK(seen == 1, "exactly one entry");
}

static void test_neighbor_payload(void)
{
    TEST("the neighbour report serialises into a frame the backend can parse");
    meshnet_t m; meshnet_init(&m, 0x20, true);
    uint8_t payload[MESH_MAX_PAYLOAD];

    CHECK(meshnet_build_neighbor_payload(&m, 1767225600u, payload, sizeof(payload),
                                         1000, 60000) == 0,
          "nothing heard yet: no report, no wasted airtime");

    for (int i = 0; i < 3; i++)
        meshnet_note_neighbor(&m, (uint16_t)(0x30 + i), (int8_t)(-60 - i), 100, 1000);

    uint16_t len = meshnet_build_neighbor_payload(&m, 1767225600u, payload,
                                                  sizeof(payload), 1000, 60000);
    CHECK(len == sizeof(neigh_hdr_t) + 3 * sizeof(neigh_entry_t), "expected size");

    uint8_t buf[SUBNET_MAX_FRAME];
    size_t n = subnet_frame_build(buf, sizeof(buf), MSG_NEIGHBOR, 0x20,
                                  ADDR_GATEWAY, 1, 4, 0, payload, len);
    CHECK(subnet_frame_parse(buf, n, NULL) == SUBNET_OK, "and it is a valid frame");

    uint16_t stale = meshnet_build_neighbor_payload(&m, 1767225600u, payload,
                                                    sizeof(payload), 1000 + 90000, 60000);
    CHECK(stale == 0, "links not heard recently are not reported as live");
}

static void test_neighbor_payload_fits_the_radio(void)
{
    TEST("a full neighbour table still fits the radio's payload budget");
    meshnet_t m; meshnet_init(&m, 0x20, true);
    for (int i = 0; i < MESH_MAX_NEIGHBORS; i++)
        meshnet_note_neighbor(&m, (uint16_t)(0x30 + i), (int8_t)(-60 - i), 100, 1000);

    uint8_t payload[MESH_MAX_PAYLOAD];
    uint16_t len = meshnet_build_neighbor_payload(&m, 1767225600u, payload,
                                                  sizeof(payload), 1000, 60000);
    CHECK(len <= MESH_MAX_PAYLOAD, "within budget");
    CHECK(MESH_HDR_LEN + len <= 64, "and the whole frame stays under 64 bytes");
}

/* -------------------------------------------------------------------- gnss */

static void test_nmea_position(void)
{
    TEST("a real GGA sentence yields the right position");
    gnss_fix_t f = {0};
    /* Captured form: ddmm.mmmm, which is not degrees -- getting this wrong puts
     * a node a few hundred kilometres from where it was planted. */
    CHECK(gnss_parse_nmea("$GPGGA,120000.00,2345.0000,N,08625.0000,E,1,09,1.2,214.0,M,0.0,M,,*5B", &f),
          "parsed");
    CHECK(f.valid, "valid");
    CHECK(f.lat_e7 == 237500000, "23 deg 45.0000' N == 23.75 deg");
    CHECK(f.lon_e7 == 864166666 || f.lon_e7 == 864166667, "86 deg 25.0000' E == 86.41667 deg");
    CHECK(f.sats == 9, "satellite count");
    CHECK(f.fix == GNSS_FIX_3D, "fix quality");
    CHECK(f.h_acc_cm == 300, "HDOP 1.2 -> ~3.0 m, and reported as an estimate");
}

static void test_nmea_southern_western(void)
{
    TEST("southern and western hemispheres get their sign");
    gnss_fix_t f = {0};
    gnss_parse_nmea("$GPGGA,120000.00,2345.0000,S,08625.0000,W,1,09,1.2,214.0,M,0.0,M,,*4B", &f);
    CHECK(f.lat_e7 < 0 && f.lon_e7 < 0, "both negative");
    CHECK(f.lat_e7 == -237500000, "magnitude preserved");
}

static void test_nmea_no_fix_is_not_a_position(void)
{
    TEST("a receiver still acquiring reports no position, not a wrong one");
    /* Quality 0 with empty lat/lon fields is what a cold receiver emits for
     * minutes. A parser that trusts it places the node off the coast of Africa. */
    gnss_fix_t f = {0};
    CHECK(gnss_parse_nmea("$GPGGA,120000.00,,,,,0,00,99.99,,,,,,*48", &f), "parsed");
    CHECK(!f.valid, "not valid");
    CHECK(f.fix == GNSS_NO_FIX, "no fix");
    CHECK(f.lat_e7 == 0 && f.lon_e7 == 0, "no position invented");
}

static void test_nmea_two_d_fix_is_downgraded(void)
{
    TEST("a 2-D fix is not allowed to masquerade as 3-D");
    /* A 2-D fix has no usable altitude, and altitude is the axis subsidence
     * lives on. The backend refuses to place a node from one. */
    gnss_fix_t f = {0};
    gnss_parse_nmea("$GPGGA,120000.00,2345.0000,N,08625.0000,E,1,04,2.0,214.0,M,0.0,M,,*55", &f);
    CHECK(f.fix == GNSS_FIX_3D, "GGA alone says 3-D");
    gnss_parse_nmea("$GPGSA,A,2,01,02,03,04,,,,,,,,,2.5,2.0,1.5*39", &f);
    CHECK(f.fix == GNSS_FIX_2D, "GSA mode 2 downgrades it");
}

static void test_nmea_time(void)
{
    TEST("RMC supplies UTC, so a node with no RTC can stamp its frames");
    gnss_fix_t f = {0};
    gnss_parse_nmea("$GPRMC,000000.00,A,2345.0000,N,08625.0000,E,0.0,0.0,010126,,,A*000", &f);
    CHECK(f.t_epoch == 1767225600u, "2026-01-01T00:00:00Z");
}

static void test_nmea_void_rmc_ignored(void)
{
    TEST("a void RMC does not set the clock");
    gnss_fix_t f = {0};
    gnss_parse_nmea("$GPRMC,120000.00,V,,,,,,,010126,,,N*00", &f);
    CHECK(f.t_epoch == 0, "no time taken from an invalid sentence");
}

static void test_nmea_garbage_is_survivable(void)
{
    TEST("garbage does not crash or produce a position");
    gnss_fix_t f = {0};
    const char *junk[] = { "", "$", "$GP", "not nmea at all",
                           "$GPGGA", "$GPGGA,,,,,,,,,,,,,,", "ÿþý" };
    for (size_t i = 0; i < sizeof(junk) / sizeof(junk[0]); i++)
        gnss_parse_nmea(junk[i], &f);
    CHECK(!f.valid, "nothing was believed");
}

static void test_distance(void)
{
    TEST("displacement distance is right at the scales that matter");
    /* Subsidence-scale movement must vanish; collapse-scale must not. */
    float mm = gnss_distance_m(237500000, 864200000, 237500001, 864200000);
    CHECK(mm < 0.05f, "1e-7 deg is about a centimetre -- invisible, correctly");

    float m100 = gnss_distance_m(237500000, 864200000, 237508993, 864200000);
    CHECK(m100 > 95.0f && m100 < 105.0f, "~100 m north measures as ~100 m");

    CHECK(gnss_distance_m(237500000, 864200000, 237500000, 864200000) == 0.0f,
          "no movement is zero");
}

/* ------------------------------------------------------------ radio limits */

static void test_llcc68_sf_limits(void)
{
    TEST("the LLCC68's spreading-factor ceiling is enforced, not assumed");
    /* The design runs SF9 at 125 kHz, which is exactly the ceiling. Every LoRa
     * tutorial reaches for SF12 when range disappoints; on this chip that is not
     * an option, and finding out by radio silence in a field is expensive. */
    CHECK(llcc68_check_sf_bw(9, LLCC68_BW_125), "SF9/BW125 -- what this system uses");
    CHECK(!llcc68_check_sf_bw(10, LLCC68_BW_125), "SF10 at 125 kHz is refused");
    CHECK(!llcc68_check_sf_bw(12, LLCC68_BW_125), "SF12 does not exist on an LLCC68");
    CHECK(!llcc68_check_sf_bw(12, LLCC68_BW_500), "not at any bandwidth");

    CHECK(llcc68_check_sf_bw(10, LLCC68_BW_250), "SF10 needs 250 kHz");
    CHECK(!llcc68_check_sf_bw(11, LLCC68_BW_250), "SF11 does not fit in 250 kHz");
    CHECK(llcc68_check_sf_bw(11, LLCC68_BW_500), "SF11 needs 500 kHz");

    CHECK(!llcc68_check_sf_bw(4, LLCC68_BW_125), "below SF5 is not a LoRa rate");
    CHECK(!llcc68_check_sf_bw(9, 0x00), "an unknown bandwidth code is refused");
}


/* ---------------------------------------------------------------- node logic */

/* A node under test: default config, a clean state, and a helper that feeds it
 * one cycle's worth of readings. */
static cfg_t test_cfg(void)
{
    cfg_t c = {
        .cfg_version = 1, .sample_interval_s = 60, .wor_period_ms = 2000,
        .tx_power_dbm = 22, .tilt_alert_mdeg = 2000, .vib_alert_mg = 500,
        .tilt_rate_alert_mdeg_h = 150, .tilt_offset_pitch = 0, .tilt_offset_roll = 0,
        .flags = CFG_FLAG_RELAY_ENABLED | CFG_FLAG_GNSS_ENABLED |
                 CFG_FLAG_VIB_ENABLED   | CFG_FLAG_DEEP_SLEEP,
    };
    c.cfg_hash = subnet_cfg_hash(&c);
    return c;
}

static void feed(nodelogic_t *s, const cfg_t *cfg, nodelogic_out_t *out,
                 uint32_t epoch, int16_t pitch, int16_t roll)
{
    nodelogic_input_t in = {
        .t_epoch = epoch, .time_valid = true,
        .pitch_mdeg = pitch, .roll_mdeg = roll, .tilt_valid = true,
        .vib_rms_mg = 10, .vib_valid = true, .vbat_mv = 3900,
    };
    nodelogic_evaluate(s, &in, cfg, out);
}

static bool has_event(const nodelogic_out_t *o, uint8_t code)
{
    for (uint8_t i = 0; i < o->n_events; i++)
        if (o->events[i].event_code == code) return true;
    return false;
}

#define BASE_EPOCH 1767225600u   /* 2026-01-01T00:00:00Z */

static void test_tilt_magnitude_uses_both_axes(void)
{
    TEST("tilt is the magnitude of both axes, not the larger one");
    /* A post leaning equally in pitch and roll is tilted by 1.41x either
     * component; reporting the smaller number under-reports every diagonal
     * movement in the field. */
    cfg_t cfg = test_cfg();
    nodelogic_t s; nodelogic_reset(&s);
    nodelogic_out_t out;
    feed(&s, &cfg, &out, BASE_EPOCH, 300, 400);
    CHECK(out.tilt_mdeg == 500, "3-4-5: pitch 300 and roll 400 is 500 mdeg");
}

static void test_offsets_are_applied(void)
{
    TEST("the calibration zero is subtracted before anything is judged");
    cfg_t cfg = test_cfg();
    cfg.tilt_offset_pitch = 1000;
    cfg.tilt_offset_roll  = -500;

    nodelogic_t s; nodelogic_reset(&s);
    nodelogic_out_t out;
    /* Exactly the pose the node was calibrated at: zero deformation, whatever
     * the raw numbers say. A hand-planted post reads mostly its own install
     * angle, and alerting on that would fire on every node the day it joins. */
    feed(&s, &cfg, &out, BASE_EPOCH, 1000, -500);
    CHECK(out.tilt_mdeg == 0, "at the calibrated pose the node reads zero tilt");
    CHECK(out.n_events == 0, "and nothing fires");
}

static void test_rate_needs_enough_history(void)
{
    TEST("no rate is reported from too little history");
    cfg_t cfg = test_cfg();
    nodelogic_t s; nodelogic_reset(&s);
    nodelogic_out_t out;

    feed(&s, &cfg, &out, BASE_EPOCH, 0, 0);
    CHECK(!out.rate_valid, "one point is not a rate");
    feed(&s, &cfg, &out, BASE_EPOCH + 60, 100, 0);
    CHECK(!out.rate_valid, "two points 60 s apart are still not a rate");
    /* Noise on a single reading is ~50 mdeg; a slope fitted across a couple of
     * minutes would be dominated by it and would fire on nothing at all. */
    feed(&s, &cfg, &out, BASE_EPOCH + 120, 200, 0);
    CHECK(!out.rate_valid, "three points inside five minutes: still refused");
}

static void test_rate_of_a_linear_ramp(void)
{
    TEST("a steady ramp reports the rate it is actually moving at");
    cfg_t cfg = test_cfg();
    cfg.tilt_rate_alert_mdeg_h = 60000;      /* out of the way for this test */
    nodelogic_t s; nodelogic_reset(&s);
    nodelogic_out_t out;

    /* 10 mdeg per minute == 600 mdeg/h, sampled once a minute for fifteen. */
    for (int i = 0; i < 15; i++)
        feed(&s, &cfg, &out, BASE_EPOCH + (uint32_t)i * 60, (int16_t)(i * 10), 0);

    CHECK(out.rate_valid, "enough history now");
    CHECK(out.tilt_rate_mdeg_h > 570 && out.tilt_rate_mdeg_h < 630,
          "600 mdeg/h, recovered from the fit");
}

static void test_rate_trigger_is_the_precursor(void)
{
    TEST("the rate threshold fires while absolute tilt is still fine");
    /* The whole early-warning claim in one test: no crack gauge, so a first
     * opening is invisible -- what is visible is tilt starting to move, and it
     * moves long before the absolute limit is anywhere near. */
    cfg_t cfg = test_cfg();
    nodelogic_t s; nodelogic_reset(&s);
    nodelogic_out_t out;

    bool fired = false;
    for (int i = 0; i < 12; i++) {
        feed(&s, &cfg, &out, BASE_EPOCH + (uint32_t)i * 60, (int16_t)(i * 5), 0);
        if (has_event(&out, EVT_TILT_RATE)) fired = true;
    }

    CHECK(out.rate_valid, "rate available");
    CHECK(out.tilt_rate_mdeg_h >= 150, "5 mdeg/min is 300 mdeg/h, over the limit");
    CHECK(fired, "the rate event fires");
    CHECK(out.tilt_mdeg < cfg.tilt_alert_mdeg,
          "and absolute tilt is still well inside its own limit");
}

static void test_event_cooldown_and_escalation(void)
{
    TEST("a node does not repeat itself, but does report getting worse");
    cfg_t cfg = test_cfg();
    nodelogic_t s; nodelogic_reset(&s);
    nodelogic_out_t out;

    uint32_t t = BASE_EPOCH;
    int fires = 0;
    for (int i = 0; i < 12; i++, t += 60) {
        feed(&s, &cfg, &out, t, (int16_t)(i * 5), 0);
        if (has_event(&out, EVT_TILT_RATE)) fires++;
    }
    CHECK(fires == 1, "a steady ramp over the limit reports itself once, not "
                      "once a minute for twelve minutes");

    /* Ten times the rate: the same criterion, a different situation, and the
     * one people act on. */
    uint8_t escalated = 0;
    for (int i = 0; i < 8; i++, t += 60) {
        feed(&s, &cfg, &out, t, (int16_t)(60 + i * 300), 0);
        for (uint8_t k = 0; k < out.n_events; k++)
            if (out.events[k].event_code == EVT_TILT_RATE &&
                out.events[k].severity > escalated)
                escalated = out.events[k].severity;
    }
    CHECK(escalated >= 2, "an escalation gets through the cooldown, at a "
                          "severity that says it got worse");
}

static void test_absolute_tilt_trigger(void)
{
    TEST("absolute tilt fires on its own threshold");
    cfg_t cfg = test_cfg();
    nodelogic_t s; nodelogic_reset(&s);
    nodelogic_out_t out;
    feed(&s, &cfg, &out, BASE_EPOCH, 2500, 0);
    CHECK(has_event(&out, EVT_TILT_ABSOLUTE), "2500 > 2000 mdeg");
    CHECK(out.events[0].value == 2500 && out.events[0].threshold == 2000,
          "the event carries both the value and the limit it crossed");
}

static void test_tamper_is_not_ground_movement(void)
{
    TEST("a step no ground could make is reported as a disturbed node");
    /* Ground does not move five degrees in sixty seconds. A post that does has
     * been knocked or pulled, and a node that reported that as subsidence would
     * poison the whole array's reconstruction. */
    cfg_t cfg = test_cfg();
    cfg.tilt_alert_mdeg = 32000;             /* keep the absolute trigger out */
    nodelogic_t s; nodelogic_reset(&s);
    nodelogic_out_t out;

    feed(&s, &cfg, &out, BASE_EPOCH, 100, 0);
    feed(&s, &cfg, &out, BASE_EPOCH + 60, 8000, 0);
    CHECK(has_event(&out, EVT_NODE_TAMPER), "a 7.9 degree step is tamper");
}

static void test_displacement_against_home(void)
{
    TEST("displacement is measured from where the node was commissioned");
    cfg_t cfg = test_cfg();
    nodelogic_t s; nodelogic_reset(&s);
    nodelogic_out_t out;

    nodelogic_input_t in = {
        .t_epoch = BASE_EPOCH, .time_valid = true, .tilt_valid = true,
        .vbat_mv = 3900, .fix_valid = true,
        .lat_e7 = 237500000, .lon_e7 = 864200000,
    };
    nodelogic_evaluate(&s, &in, &cfg, &out);
    CHECK(s.home_valid, "the first good fix becomes home");
    CHECK(!has_event(&out, EVT_DISPLACEMENT), "and does not itself raise anything");

    /* Metre-scale wander is all a NEO-6M can resolve and it is not subsidence;
     * the threshold sits well above it. */
    in.t_epoch += 600;
    in.lat_e7 += 500;                        /* ~5 m north */
    nodelogic_evaluate(&s, &in, &cfg, &out);
    CHECK(!has_event(&out, EVT_DISPLACEMENT), "5 m of GNSS wander is not an event");

    in.t_epoch += 600;
    in.lat_e7 += 4000;                       /* ~45 m from home */
    nodelogic_evaluate(&s, &in, &cfg, &out);
    CHECK(has_event(&out, EVT_DISPLACEMENT), "45 m is a collapse or a theft");
}

static void test_battery_hysteresis(void)
{
    TEST("a solar node does not report low battery twice a day");
    cfg_t cfg = test_cfg();
    nodelogic_t s; nodelogic_reset(&s);
    nodelogic_out_t out;
    nodelogic_input_t in = {
        .t_epoch = BASE_EPOCH, .time_valid = true, .tilt_valid = true,
        .vib_valid = true, .vbat_mv = 3350,
    };
    nodelogic_evaluate(&s, &in, &cfg, &out);
    CHECK(out.flags & TLM_FLAG_LOW_BATTERY, "3350 mV is low");
    CHECK(has_event(&out, EVT_LOW_BATTERY), "and is reported");

    /* Recovering to just above the trigger must not clear the latch, or a panel
     * charging at dawn produces one clear and one warning every day. */
    in.t_epoch += 3600; in.vbat_mv = 3450;
    nodelogic_evaluate(&s, &in, &cfg, &out);
    CHECK(out.flags & TLM_FLAG_LOW_BATTERY, "still latched just above the trigger");

    in.t_epoch += 3600; in.vbat_mv = 3600;
    nodelogic_evaluate(&s, &in, &cfg, &out);
    CHECK(!(out.flags & TLM_FLAG_LOW_BATTERY), "cleared once genuinely recovered");
}

static void test_no_clock_no_invented_rates(void)
{
    TEST("with no clock the node measures and reports, and invents nothing");
    cfg_t cfg = test_cfg();
    nodelogic_t s; nodelogic_reset(&s);
    nodelogic_out_t out;
    nodelogic_input_t in = {
        .t_epoch = 0, .time_valid = false,
        .pitch_mdeg = 9000, .roll_mdeg = 0, .tilt_valid = true,
        .vib_rms_mg = 4000, .vib_valid = true, .vbat_mv = 3100,
    };
    nodelogic_evaluate(&s, &in, &cfg, &out);
    CHECK(out.tilt_mdeg == 9000, "the measurement still happens");
    CHECK(out.n_events == 0, "no events: every threshold here is timed");
    CHECK(!out.rate_valid, "and no rate is claimed");
}

static void test_sensor_faults_are_flagged(void)
{
    TEST("a dead sensor is reported as dead, not as a reading of zero");
    cfg_t cfg = test_cfg();
    nodelogic_t s; nodelogic_reset(&s);
    nodelogic_out_t out;
    nodelogic_input_t in = { .t_epoch = BASE_EPOCH, .time_valid = true };
    nodelogic_evaluate(&s, &in, &cfg, &out);
    CHECK(out.flags & TLM_FLAG_TILT_FAULT, "tilt fault");
    CHECK(out.flags & TLM_FLAG_VIB_FAULT, "vibration fault");
    CHECK(out.flags & TLM_FLAG_GNSS_FAULT, "gnss fault");
    CHECK(out.flags & TLM_FLAG_UNCALIBRATED, "and an uncalibrated node says so");
}

static void test_severity_scales_with_the_breach(void)
{
    TEST("severity reflects how far past the limit a reading is");
    CHECK(nodelogic_severity(160, 150) == 1, "just over: a warning");
    CHECK(nodelogic_severity(300, 150) == 2, "twice the limit: high");
    CHECK(nodelogic_severity(600, 150) == 3, "four times: critical");
    CHECK(nodelogic_severity(-600, 150) == 3, "sign does not soften it");
}

static void test_battery_percentage(void)
{
    TEST("the battery curve is monotonic and bounded");
    CHECK(nodelogic_battery_pct(2900) == 0, "flat");
    CHECK(nodelogic_battery_pct(4200) == 100, "full");
    uint8_t last = 0;
    for (uint16_t mv = 2900; mv <= 4200; mv += 25) {
        uint8_t pct = nodelogic_battery_pct(mv);
        CHECK(pct >= last, "never goes backwards");
        last = pct;
    }
}

/* -------------------------------------------------------- gateway rules */

static void test_gateway_texts_on_a_critical_event(void)
{
    TEST("a critical event becomes an SMS with no server involved");
    gwrules_t g; gwrules_init(&g, NULL);
    char sms[GWRULES_SMS_LEN];

    evt_t e = { .t_epoch = BASE_EPOCH, .event_code = EVT_TILT_RATE,
                .severity = 3, .value = 900, .threshold = 150 };
    CHECK(gwrules_on_event(&g, 0x0014, &e, BASE_EPOCH, sms, sizeof(sms)),
          "the message is produced");
    CHECK(strstr(sms, "0x0014") != NULL, "it names the node");
    CHECK(strstr(sms, "TILT RATE") != NULL, "and what happened");
    CHECK(strstr(sms, "900") != NULL, "and the value");
    CHECK(strlen(sms) < GWRULES_SMS_LEN, "and fits one message");
}

static void test_gateway_ignores_noise(void)
{
    TEST("a low-severity event is logged, not texted");
    gwrules_t g; gwrules_init(&g, NULL);
    char sms[GWRULES_SMS_LEN];
    evt_t e = { .t_epoch = BASE_EPOCH, .event_code = EVT_VIBRATION,
                .severity = 1, .value = 600, .threshold = 500 };
    CHECK(!gwrules_on_event(&g, 0x0014, &e, BASE_EPOCH, sms, sizeof(sms)),
          "no SMS for a node noting plant traffic");
    CHECK(g.suppressed == 1, "counted as suppressed, not silently dropped");
}

static void test_gateway_cooldown(void)
{
    TEST("one node cannot text the same people every minute");
    gwrules_t g; gwrules_init(&g, NULL);
    char sms[GWRULES_SMS_LEN];
    evt_t e = { .t_epoch = BASE_EPOCH, .event_code = EVT_TILT_RATE,
                .severity = 2, .value = 300, .threshold = 150 };

    CHECK(gwrules_on_event(&g, 0x0014, &e, BASE_EPOCH, sms, sizeof(sms)), "first");
    CHECK(!gwrules_on_event(&g, 0x0014, &e, BASE_EPOCH + 60, sms, sizeof(sms)),
          "not a minute later");
    /* An early-warning system that repeats itself gets muted by the people it
     * exists to warn, and a muted system is worse than none. */
    e.severity = 3;
    CHECK(gwrules_on_event(&g, 0x0014, &e, BASE_EPOCH + 120, sms, sizeof(sms)),
          "but an escalation gets through the cooldown");
    CHECK(gwrules_on_event(&g, 0x0015, &e, BASE_EPOCH + 120, sms, sizeof(sms)),
          "and another node is not affected by this one's cooldown");
}

static void test_gateway_defers_to_the_backend_while_it_can(void)
{
    TEST("telemetry is judged locally only once the backend is unreachable");
    gwrules_t g; gwrules_init(&g, NULL);
    char sms[GWRULES_SMS_LEN];

    tlm_t t = { .t_epoch = BASE_EPOCH, .pitch_mdeg = 9000, .roll_mdeg = 0 };

    gwrules_note_uplink_ok(&g, BASE_EPOCH);
    CHECK(!gwrules_link_is_down(&g, BASE_EPOCH + 10), "link is up");
    CHECK(!gwrules_on_telemetry(&g, 0x0014, &t, BASE_EPOCH + 10, sms, sizeof(sms)),
          "the backend owns this judgement: it has the baseline and the array");

    /* Five minutes with nothing getting through, and the gateway starts
     * deciding for itself -- crudely, with no baseline, which is why the
     * threshold it uses is a blunt one. */
    CHECK(gwrules_link_is_down(&g, BASE_EPOCH + 600), "link is down");
    CHECK(gwrules_on_telemetry(&g, 0x0014, &t, BASE_EPOCH + 600, sms, sizeof(sms)),
          "now it acts alone");
    CHECK(strstr(sms, "0x0014") != NULL, "and names the node");
}

static void test_gateway_link_down_from_cold(void)
{
    TEST("a gateway that has never reached the backend knows it");
    gwrules_t g; gwrules_init(&g, NULL);
    CHECK(gwrules_link_is_down(&g, BASE_EPOCH),
          "booting next to a dead router is the link being down, not being new");
}


/* -------------------------------------------------------- status indicator */

/* A gateway with nothing wrong: radio up, field talking, modem registered,
 * network up, backend answering, spool empty. */
static statusled_input_t healthy(void)
{
    return (statusled_input_t){
        .radio_up = true, .wifi_up = true, .backend_ok = true,
        .modem_ready = true, .modem_registered = true,
        .spool_depth = 0, .quiet_s = 5, .uptime_s = 3600,
    };
}

static void test_led_reports_the_worst_thing(void)
{
    TEST("the indicator reports the worst fault, not an average of them");
    /* A gateway with a dead radio and a fine backhaul is a dead gateway.
     * Summarising the two into something reassuring would be a lie told in the
     * field, where lies are expensive. */
    statusled_input_t in = healthy();
    in.radio_up = false;
    in.wifi_up = false;
    in.backend_ok = false;
    in.modem_ready = false;
    CHECK(statusled_evaluate(&in) == LED_RADIO_DOWN, "the radio outranks everything");

    in.radio_up = true;
    CHECK(statusled_evaluate(&in) == LED_NO_MODEM,
          "with the radio up, the offline alerting path is the next worst loss");

    in.modem_ready = true; in.modem_registered = true;
    CHECK(statusled_evaluate(&in) == LED_NO_WIFI, "then the network");

    in.wifi_up = true;
    CHECK(statusled_evaluate(&in) == LED_BACKEND_DOWN, "then the backend");

    in.backend_ok = true;
    CHECK(statusled_evaluate(&in) == LED_OK, "and then nothing is wrong");
}

static void test_led_silent_field_beats_a_lost_backhaul(void)
{
    TEST("a silent field ranks above a lost backhaul");
    /* Losing the backhaul delays frames the gateway already has. Hearing
     * nothing at all means there are no frames -- the antenna, or the field. */
    statusled_input_t in = healthy();
    in.quiet_s = STATUSLED_QUIET_S + 1;
    in.backend_ok = false;
    CHECK(statusled_evaluate(&in) == LED_FIELD_SILENT, "silence wins");
}

static void test_led_settles_before_complaining(void)
{
    TEST("a just-booted gateway is not accused of a silent field");
    /* Nodes report on a 60 s duty cycle, so a gateway that has been up for ten
     * seconds and heard nobody is not a fault, it is a gateway that has been up
     * for ten seconds. */
    statusled_input_t in = healthy();
    in.uptime_s = 10;
    in.quiet_s = 0xFFFFFFFFu;          /* nothing heard, ever */
    CHECK(statusled_evaluate(&in) == LED_OK, "quiet during the settling window is fine");

    in.uptime_s = STATUSLED_SETTLE_S + 1;
    CHECK(statusled_evaluate(&in) == LED_FIELD_SILENT,
          "past it, silence from the whole field is a fault");
}

static void test_led_spool_depth(void)
{
    TEST("a deep spool is reported, a shallow one is not");
    /* Spooling is the design working. Spooling this deep means the outage has
     * lasted long enough that data is about to be shed. */
    statusled_input_t in = healthy();
    in.spool_depth = STATUSLED_SPOOL_DEEP - 1;
    CHECK(statusled_evaluate(&in) == LED_OK, "a backlog is normal");
    in.spool_depth = STATUSLED_SPOOL_DEEP;
    CHECK(statusled_evaluate(&in) == LED_SPOOL_FILLING, "a deep one is not");
}

static void test_led_codes_are_distinguishable(void)
{
    TEST("every code has a distinct blink count, a tag and an explanation");
    /* The blink count is the entire user interface of this device at night;
     * two codes sharing one would make the display ambiguous. */
    for (int a = 0; a < LED_CODE_COUNT; a++) {
        CHECK(statusled_tag((statusled_code_t)a)[0] != '\0', "has a tag");
        CHECK(statusled_meaning((statusled_code_t)a)[0] != '\0', "has an explanation");
        for (int b = a + 1; b < LED_CODE_COUNT; b++)
            CHECK(statusled_blinks((statusled_code_t)a) != statusled_blinks((statusled_code_t)b),
                  "no two codes blink the same number of times");
    }
    CHECK(statusled_blinks(LED_RADIO_DOWN) == 0,
          "the fatal one is a continuous flash, not a count to be read");
    CHECK(statusled_blinks(LED_OK) == 1, "healthy is a single heartbeat");
}

int main(void)
{
    printf("\nfirmware portable-core tests\n\n");
    printf("frame codec\n");
    test_roundtrip();
    test_all_types_roundtrip();
    test_corruption_is_caught();
    test_wrong_length_for_type_is_rejected();
    test_oversize_payload_refused();
    test_neighbor_variable_length();
    test_rehop_keeps_the_frame_valid();
    test_config_hash();

    printf("\nmesh routing\n");
    test_flood_terminates();
    test_own_frame_is_not_relayed();
    test_ttl_expiry();
    test_ttl_decrements_across_hops();
    test_addressed_frames();
    test_relay_disabled_node_still_receives_its_own_mail();
    test_seen_cache_ages_out();
    test_seen_cache_survives_millis_wrap();
    test_seen_cache_holds_a_whole_field();
    test_neighbor_table_keeps_the_strongest();
    test_neighbor_updates_in_place();
    test_neighbor_payload();
    test_neighbor_payload_fits_the_radio();

    printf("\ngnss\n");
    test_nmea_position();
    test_nmea_southern_western();
    test_nmea_no_fix_is_not_a_position();
    test_nmea_two_d_fix_is_downgraded();
    test_nmea_time();
    test_nmea_void_rmc_ignored();
    test_nmea_garbage_is_survivable();
    test_distance();

    printf("\nradio limits\n");
    test_llcc68_sf_limits();

    printf("\nnode logic\n");
    test_tilt_magnitude_uses_both_axes();
    test_offsets_are_applied();
    test_rate_needs_enough_history();
    test_rate_of_a_linear_ramp();
    test_rate_trigger_is_the_precursor();
    test_event_cooldown_and_escalation();
    test_absolute_tilt_trigger();
    test_tamper_is_not_ground_movement();
    test_displacement_against_home();
    test_battery_hysteresis();
    test_no_clock_no_invented_rates();
    test_sensor_faults_are_flagged();
    test_severity_scales_with_the_breach();
    test_battery_percentage();

    printf("\nstatus indicator\n");
    test_led_reports_the_worst_thing();
    test_led_silent_field_beats_a_lost_backhaul();
    test_led_settles_before_complaining();
    test_led_spool_depth();
    test_led_codes_are_distinguishable();

    printf("\ngateway rules\n");
    test_gateway_texts_on_a_critical_event();
    test_gateway_ignores_noise();
    test_gateway_cooldown();
    test_gateway_defers_to_the_backend_while_it_can();
    test_gateway_link_down_from_cold();

    printf("\n%d checks, %d failures\n\n", checks, failures);
    return failures ? 1 : 0;
}
