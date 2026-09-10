/* Frames built by the *firmware's* encoder, for Python to diff against.
 *
 * proto_check.c already proves the C structs match. This proves the code the
 * node actually transmits with -- subnet_frame_build(), which assembles the
 * header and computes the CRC over two discontiguous spans -- emits the same
 * bytes the backend expects. Those are different pieces of code, and only one
 * of them ships on the hardware.
 */
#include <stdio.h>
#include <string.h>
#include "subnet_proto.h"

static void dump(const char *label, const uint8_t *b, size_t n)
{
    printf("%s=", label);
    for (size_t i = 0; i < n; i++) printf("%02x", b[i]);
    printf("\n");
}

int main(void)
{
    uint8_t buf[SUBNET_MAX_FRAME];
    size_t n;

    tlm_t t = { .t_epoch = 1767225600u, .pitch_mdeg = -1234, .roll_mdeg = 5678,
                .vib_rms_mg = 412, .vib_peak_hz = 37, .temp_c_x100 = 2735,
                .n_samples = 32, .gnss_status = GNSS_STATUS(GNSS_FIX_3D, 9),
                .vbat_mv = 3987, .rssi = -87, .snr = 122,
                .flags = TLM_FLAG_RELAYED | TLM_FLAG_LOW_BATTERY, .reserved = 0 };
    n = subnet_frame_build(buf, sizeof(buf), MSG_TELEMETRY, 0x42, ADDR_GATEWAY,
                           0x1337, MESH_DEFAULT_TTL, 2, &t, sizeof(t));
    dump("telemetry", buf, n);

    evt_t e = { .t_epoch = 1767225600u, .event_code = EVT_TILT_ACCEL,
                .severity = 3, .value = -4200, .threshold = 2000 };
    n = subnet_frame_build(buf, sizeof(buf), MSG_EVENT, 0x07, ADDR_GATEWAY,
                           9, MESH_DEFAULT_TTL, 0, &e, sizeof(e));
    dump("event", buf, n);

    pos_t p = { .t_epoch = 1767225600u, .lat_e7 = 236780000, .lon_e7 = 863950000,
                .alt_m = 214, .h_acc_cm = 250,
                .gnss_status = GNSS_STATUS(GNSS_FIX_3D, 11) };
    n = subnet_frame_build(buf, sizeof(buf), MSG_POSITION, 0x21, ADDR_GATEWAY,
                           5, MESH_DEFAULT_TTL, 0, &p, sizeof(p));
    dump("position", buf, n);

    cfg_t c = { .cfg_version = 1, .sample_interval_s = 60, .wor_period_ms = 2000,
                .tx_power_dbm = 22, .tilt_alert_mdeg = 2000, .vib_alert_mg = 500,
                .tilt_rate_alert_mdeg_h = 150, .tilt_offset_pitch = 0,
                .tilt_offset_roll = 0, .flags = 0x0F, .cfg_hash = 0 };
    c.cfg_hash = subnet_cfg_hash(&c);
    printf("cfg_hash=%04x\n", c.cfg_hash);
    n = subnet_frame_build(buf, sizeof(buf), MSG_CONFIG_SET, ADDR_GATEWAY, 0x10,
                           3, MESH_DEFAULT_TTL, 0, &c, sizeof(c));
    dump("config", buf, n);

    cfg_ack_t a = { .t_epoch = 1767225600u, .cfg_version = 1,
                    .cfg_hash = c.cfg_hash, .status = CFG_STATUS_APPLIED };
    n = subnet_frame_build(buf, sizeof(buf), MSG_CONFIG_ACK, 0x10, ADDR_GATEWAY,
                           4, MESH_DEFAULT_TTL, 1, &a, sizeof(a));
    dump("config_ack", buf, n);
    return 0;
}
