/*
 * SUBSIDENCE-NET mesh wire protocol  --  v1
 *
 * Single source of truth for the over-the-air frame format. Mirrored byte-for-byte
 * by backend/app/proto.py; backend/tests/test_proto.py checks both against the same
 * golden vectors in docs/golden_frames.json.
 *
 * Radio: EByte E220-900M22S, India WPC de-licensed ISM band 865-867 MHz.
 * All multi-byte fields are LITTLE-ENDIAN (native ESP32 order, no swapping needed).
 * Structs are packed; do not reorder fields without regenerating golden vectors.
 */
#ifndef SUBNET_MESH_PROTO_H
#define SUBNET_MESH_PROTO_H

#include <stdint.h>

#define SUBNET_MAGIC        0x5B
#define SUBNET_PROTO_VER    0x1

/* Reserved addresses */
#define ADDR_GATEWAY        0x0001
#define ADDR_BROADCAST      0xFFFF
#define ADDR_UNASSIGNED     0x0000

/* Message types (low nibble of ver_type) */
#define MSG_TELEMETRY       0x1   /* up   */
#define MSG_EVENT           0x2   /* up   - bypasses duty cycle */
#define MSG_CONFIG_SET      0x3   /* down - remote reconfiguration */
#define MSG_CONFIG_ACK      0x4   /* up   */
#define MSG_NEIGHBOR        0x5   /* up   - RSSI table -> topology graph */
#define MSG_TIME_SYNC       0x6   /* down - nodes have no RTC */
#define MSG_POSITION        0x7   /* up   - GNSS fix, low rate */

#define VER_TYPE(v, t)      (uint8_t)(((v) << 4) | ((t) & 0x0F))
#define VT_VERSION(vt)      (uint8_t)((vt) >> 4)
#define VT_TYPE(vt)         (uint8_t)((vt) & 0x0F)

#define MESH_HDR_LEN        12
#define MESH_MAX_PAYLOAD    52    /* keeps worst-case frame <= 64 B at SF9 */
#define MESH_DEFAULT_TTL    4     /* covers a 15-node field comfortably */

/* ---------------------------------------------------------------- header */
typedef struct __attribute__((packed)) {
    uint8_t  magic;      /* SUBNET_MAGIC                                    */
    uint8_t  ver_type;   /* high nibble = version, low nibble = msg type    */
    uint16_t src;        /* originating node address                        */
    uint16_t dst;        /* ADDR_GATEWAY / ADDR_BROADCAST / node            */
    uint16_t seq;        /* per-source counter, drives flood de-duplication */
    uint8_t  ttl;        /* decremented each hop, frame dropped at 0        */
    uint8_t  hops;       /* incremented each hop, reported as path length   */
    uint16_t crc16;      /* CCITT-FALSE over hdr[0..9] + payload            */
} mesh_hdr_t;

/* ------------------------------------------------------------- payloads */

/* MSG_TELEMETRY - 22 B. Node-side feature extraction already applied. */
typedef struct __attribute__((packed)) {
    uint32_t t_epoch;       /* unix seconds, disciplined by MSG_TIME_SYNC   */
    int16_t  pitch_mdeg;    /* milli-degrees, gravity vector from LIS3DH    */
    int16_t  roll_mdeg;     /* milli-degrees                                */
    uint16_t vib_rms_mg;    /* RMS acceleration over sample window, milli-g */
    uint16_t vib_peak_hz;   /* dominant frequency from on-node FFT          */
    int16_t  temp_c_x100;   /* LIS3DH die temp, centi-C -- drift correction */
    uint8_t  n_samples;     /* raw samples averaged into this frame         */
    uint8_t  gnss_status;   /* [1:0] fix quality, [7:2] satellite count     */
    uint16_t vbat_mv;       /* battery millivolts                           */
    int8_t   rssi;          /* last received RSSI, dBm                      */
    uint8_t  snr;           /* last received SNR, (dB + 20) * 4             */
    uint8_t  flags;         /* see TLM_FLAG_*                               */
    uint8_t  reserved;
} tlm_t;

#define TLM_FLAG_TILT_FAULT   (1u << 0)
#define TLM_FLAG_GNSS_FAULT   (1u << 1)
#define TLM_FLAG_VIB_FAULT    (1u << 2)
#define TLM_FLAG_UNCALIBRATED (1u << 3)
#define TLM_FLAG_LOW_BATTERY  (1u << 4)
#define TLM_FLAG_RELAYED      (1u << 5)   /* node acted as a relay this cycle */

/* gnss_status low 2 bits */
#define GNSS_NO_FIX         0
#define GNSS_FIX_2D         1
#define GNSS_FIX_3D         2
#define GNSS_FIX_DGPS       3
#define GNSS_STATUS(fix, sats) (uint8_t)(((fix) & 0x03) | (((sats) & 0x3F) << 2))

/* MSG_EVENT - 14 B. Threshold breach detected on-node; sent immediately. */
typedef struct __attribute__((packed)) {
    uint32_t t_epoch;
    uint8_t  event_code;    /* see EVT_*                                    */
    uint8_t  severity;      /* 0 info .. 3 critical                         */
    int32_t  value;         /* event-specific, milli-units                  */
    int32_t  threshold;     /* the threshold that was crossed               */
} evt_t;

#define EVT_TILT_RATE       0x01
#define EVT_TILT_ABSOLUTE   0x02
#define EVT_TILT_ACCEL      0x03  /* tilt rate rising: precursor */
#define EVT_VIBRATION       0x04
#define EVT_DISPLACEMENT    0x05  /* GNSS: moved metres          */
#define EVT_NODE_TAMPER     0x06
#define EVT_LOW_BATTERY     0x07

/* MSG_POSITION - 17 B. GNSS fix. Sent at commissioning, then only on change.
 * Not a subsidence measurement: a NEO-6M is metre-scale, subsidence is mm-scale.
 * It localises the node, supplies the baselines strain is divided by, and flags
 * gross displacement (collapse or theft).                                     */
typedef struct __attribute__((packed)) {
    uint32_t t_epoch;
    int32_t  lat_e7;        /* degrees * 1e7                                */
    int32_t  lon_e7;
    int16_t  alt_m;         /* metres above ellipsoid                       */
    uint16_t h_acc_cm;      /* horizontal accuracy estimate, centimetres    */
    uint8_t  gnss_status;   /* [1:0] fix quality, [7:2] satellite count     */
} pos_t;

/* MSG_CONFIG_SET - 20 B. Pushed from the dashboard, persisted to NVS. */
typedef struct __attribute__((packed)) {
    uint16_t cfg_version;      /* monotonic, assigned by backend            */
    uint16_t sample_interval_s;
    uint16_t wor_period_ms;    /* E220 wake-on-radio listen cadence         */
    uint8_t  tx_power_dbm;     /* 10 / 13 / 17 / 22                         */
    uint16_t tilt_alert_mdeg;
    uint16_t vib_alert_mg;
    uint16_t tilt_rate_alert_mdeg_h; /* primary early-warning trigger        */
    int16_t  tilt_offset_pitch; /* zero-offset calibration, milli-degrees   */
    int16_t  tilt_offset_roll;
    uint8_t  flags;             /* see CFG_FLAG_*                           */
    uint16_t cfg_hash;          /* CRC16 of fields above, echoed in the ACK */
} cfg_t;

#define CFG_FLAG_RELAY_ENABLED  (1u << 0)
#define CFG_FLAG_GNSS_ENABLED   (1u << 1)
#define CFG_FLAG_VIB_ENABLED    (1u << 2)
#define CFG_FLAG_DEEP_SLEEP     (1u << 3)
#define CFG_FLAG_RECALIBRATE    (1u << 4)   /* one-shot: re-zero the tilt   */

/* MSG_CONFIG_ACK - 9 B. */
typedef struct __attribute__((packed)) {
    uint32_t t_epoch;
    uint16_t cfg_version;
    uint16_t cfg_hash;      /* must match the pushed config                 */
    uint8_t  status;        /* see CFG_STATUS_*                             */
} cfg_ack_t;

#define CFG_STATUS_APPLIED   0
#define CFG_STATUS_REJECTED  1
#define CFG_STATUS_PARTIAL   2

/* MSG_NEIGHBOR - 5 B header + 4 B per entry. Builds the topology graph. */
typedef struct __attribute__((packed)) {
    uint16_t addr;
    int8_t   rssi;
    uint8_t  snr;
} neigh_entry_t;

typedef struct __attribute__((packed)) {
    uint32_t t_epoch;
    uint8_t  count;         /* number of neigh_entry_t that follow          */
} neigh_hdr_t;

#define MESH_MAX_NEIGHBORS  8

/* MSG_TIME_SYNC - 6 B. */
typedef struct __attribute__((packed)) {
    uint32_t t_epoch;
    uint16_t t_millis;
} timesync_t;

/* ------------------------------------------------------------------ CRC */
/* CRC16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no xor-out. */
static inline uint16_t mesh_crc16(const uint8_t *data, uint16_t len)
{
    uint16_t crc = 0xFFFF;
    for (uint16_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (uint8_t b = 0; b < 8; b++)
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
    }
    return crc;
}

#endif /* SUBNET_MESH_PROTO_H */
