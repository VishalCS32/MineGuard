/* Cross-language conformance harness.
 *
 * Compiled and run by test_proto.py. Emits the C side's view of the wire format
 * so Python can assert it matches byte for byte. If firmware and backend ever
 * drift apart, this is what catches it -- before it costs a field deployment.
 */
#include <stdio.h>
#include <string.h>
#include "mesh_proto.h"

static void put_hex(const char *label, const uint8_t *b, uint16_t n)
{
    printf("%s=", label);
    for (uint16_t i = 0; i < n; i++) printf("%02x", b[i]);
    printf("\n");
}

int main(void)
{
    printf("sizeof_hdr=%zu\n",     sizeof(mesh_hdr_t));
    printf("sizeof_tlm=%zu\n",     sizeof(tlm_t));
    printf("sizeof_evt=%zu\n",     sizeof(evt_t));
    printf("sizeof_cfg=%zu\n",     sizeof(cfg_t));
    printf("sizeof_cfg_ack=%zu\n", sizeof(cfg_ack_t));
    printf("sizeof_timesync=%zu\n", sizeof(timesync_t));
    printf("sizeof_neigh_hdr=%zu\n", sizeof(neigh_hdr_t));
    printf("sizeof_neigh_entry=%zu\n", sizeof(neigh_entry_t));

    /* CRC reference vectors */
    printf("crc_check123456789=%04x\n", mesh_crc16((const uint8_t *)"123456789", 9));
    printf("crc_empty=%04x\n", mesh_crc16((const uint8_t *)"", 0));

    /* A fully built telemetry frame, exactly as a node would transmit it. */
    tlm_t t = {
        .t_epoch     = 1767225600u,   /* 2026-01-01T00:00:00Z */
        .pitch_mdeg  = -1234,
        .roll_mdeg   = 5678,
        .vib_rms_mg  = 412,
        .vib_peak_hz = 37,
        .tof_mm      = 2450,
        .crack_ohm   = 1500,
        .vbat_mv     = 3987,
        .rssi        = -87,
        .snr         = 122,
        .flags       = TLM_FLAG_RELAYED | TLM_FLAG_LOW_BATTERY,
        .reserved    = 0,
    };

    uint8_t frame[MESH_HDR_LEN + sizeof(tlm_t)];
    mesh_hdr_t *h = (mesh_hdr_t *)frame;
    h->magic    = SUBNET_MAGIC;
    h->ver_type = VER_TYPE(SUBNET_PROTO_VER, MSG_TELEMETRY);
    h->src      = 0x0042;
    h->dst      = ADDR_GATEWAY;
    h->seq      = 0x1337;
    h->ttl      = MESH_DEFAULT_TTL;
    h->hops     = 2;
    h->crc16    = 0;
    memcpy(frame + MESH_HDR_LEN, &t, sizeof(t));
    /* CRC covers header bytes 0..9 (all but the CRC field) plus the payload. */
    uint8_t crc_in[10 + sizeof(tlm_t)];
    memcpy(crc_in, frame, 10);
    memcpy(crc_in + 10, frame + MESH_HDR_LEN, sizeof(t));
    h->crc16 = mesh_crc16(crc_in, sizeof(crc_in));

    put_hex("frame_telemetry", frame, sizeof(frame));
    return 0;
}
