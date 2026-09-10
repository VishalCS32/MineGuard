#include <string.h>

#include "subnet_proto.h"

/* Wire layout: hdr[0..9] | crc16 [10..11] | payload. The CRC sits inside the
 * 12-byte header but covers only what precedes it plus the payload, so it is
 * computed over two discontiguous spans -- hence the explicit offsets here
 * rather than a memcpy of mesh_hdr_t. */
#define OFF_MAGIC     0
#define OFF_VER_TYPE  1
#define OFF_SRC       2
#define OFF_DST       4
#define OFF_SEQ       6
#define OFF_TTL       8
#define OFF_HOPS      9
#define OFF_CRC      10
#define CRC_PREFIX   10   /* bytes of header the CRC covers */

static inline uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static inline void     wr16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }

const char *subnet_strerror(subnet_err_t err)
{
    switch (err) {
    case SUBNET_OK:            return "ok";
    case SUBNET_ERR_SHORT:     return "runt frame";
    case SUBNET_ERR_MAGIC:     return "bad magic";
    case SUBNET_ERR_VERSION:   return "unsupported version";
    case SUBNET_ERR_CRC:       return "bad crc";
    case SUBNET_ERR_LENGTH:    return "payload length wrong for type";
    case SUBNET_ERR_TOO_BIG:   return "payload exceeds radio budget";
    default:                   return "unknown";
    }
}

uint16_t subnet_payload_len(uint8_t msg_type)
{
    switch (msg_type) {
    case MSG_TELEMETRY:  return sizeof(tlm_t);
    case MSG_EVENT:      return sizeof(evt_t);
    case MSG_CONFIG_SET: return sizeof(cfg_t);
    case MSG_CONFIG_ACK: return sizeof(cfg_ack_t);
    case MSG_TIME_SYNC:  return sizeof(timesync_t);
    case MSG_POSITION:   return sizeof(pos_t);
    case MSG_NEIGHBOR:   return 0;   /* variable: header + count * entry */
    default:             return 0;
    }
}

/* CRC over hdr[0..9] followed by the payload. Both spans, one running CRC --
 * writing it this way avoids a scratch buffer on a device with 2 MB of RAM but
 * a strong preference for not fragmenting it. */
static uint16_t crc_over(const uint8_t *hdr, const uint8_t *payload, uint16_t payload_len)
{
    uint16_t crc = 0xFFFF;
    for (uint16_t i = 0; i < CRC_PREFIX; i++) {
        crc ^= (uint16_t)hdr[i] << 8;
        for (uint8_t b = 0; b < 8; b++)
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
    }
    for (uint16_t i = 0; i < payload_len; i++) {
        crc ^= (uint16_t)payload[i] << 8;
        for (uint8_t b = 0; b < 8; b++)
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
    }
    return crc;
}

size_t subnet_frame_build(uint8_t *out, size_t out_cap,
                          uint8_t msg_type, uint16_t src, uint16_t dst,
                          uint16_t seq, uint8_t ttl, uint8_t hops,
                          const void *payload, uint16_t payload_len)
{
    if (payload_len > MESH_MAX_PAYLOAD) return 0;
    if (out_cap < (size_t)MESH_HDR_LEN + payload_len) return 0;

    out[OFF_MAGIC]    = SUBNET_MAGIC;
    out[OFF_VER_TYPE] = VER_TYPE(SUBNET_PROTO_VER, msg_type);
    wr16(out + OFF_SRC, src);
    wr16(out + OFF_DST, dst);
    wr16(out + OFF_SEQ, seq);
    out[OFF_TTL]  = ttl;
    out[OFF_HOPS] = hops;

    if (payload_len && payload) memcpy(out + MESH_HDR_LEN, payload, payload_len);
    wr16(out + OFF_CRC, crc_over(out, out + MESH_HDR_LEN, payload_len));
    return (size_t)MESH_HDR_LEN + payload_len;
}

subnet_err_t subnet_frame_parse(const uint8_t *buf, size_t len, subnet_frame_t *out)
{
    if (len < MESH_HDR_LEN)          return SUBNET_ERR_SHORT;
    if (len > SUBNET_MAX_FRAME)      return SUBNET_ERR_TOO_BIG;
    if (buf[OFF_MAGIC] != SUBNET_MAGIC) return SUBNET_ERR_MAGIC;

    uint8_t version = VT_VERSION(buf[OFF_VER_TYPE]);
    uint8_t type    = VT_TYPE(buf[OFF_VER_TYPE]);
    if (version != SUBNET_PROTO_VER) return SUBNET_ERR_VERSION;

    uint16_t payload_len = (uint16_t)(len - MESH_HDR_LEN);
    if (rd16(buf + OFF_CRC) != crc_over(buf, buf + MESH_HDR_LEN, payload_len))
        return SUBNET_ERR_CRC;

    /* A frame whose payload is the wrong size for its type would be cast onto
     * the wrong struct and read as plausible garbage. Reject it instead. */
    uint16_t expect = subnet_payload_len(type);
    if (expect && payload_len != expect) return SUBNET_ERR_LENGTH;
    if (type == MSG_NEIGHBOR) {
        if (payload_len < sizeof(neigh_hdr_t)) return SUBNET_ERR_LENGTH;
        const neigh_hdr_t *nh = (const neigh_hdr_t *)(buf + MESH_HDR_LEN);
        if (nh->count > MESH_MAX_NEIGHBORS) return SUBNET_ERR_LENGTH;
        if (payload_len != sizeof(neigh_hdr_t) + (uint16_t)nh->count * sizeof(neigh_entry_t))
            return SUBNET_ERR_LENGTH;
    }

    if (out) {
        out->type        = type;
        out->version     = version;
        out->src         = rd16(buf + OFF_SRC);
        out->dst         = rd16(buf + OFF_DST);
        out->seq         = rd16(buf + OFF_SEQ);
        out->ttl         = buf[OFF_TTL];
        out->hops        = buf[OFF_HOPS];
        out->payload     = buf + MESH_HDR_LEN;
        out->payload_len = payload_len;
    }
    return SUBNET_OK;
}

void subnet_frame_rehop(uint8_t *buf, size_t len, uint8_t ttl, uint8_t hops)
{
    if (len < MESH_HDR_LEN) return;
    buf[OFF_TTL]  = ttl;
    buf[OFF_HOPS] = hops;
    wr16(buf + OFF_CRC, crc_over(buf, buf + MESH_HDR_LEN, (uint16_t)(len - MESH_HDR_LEN)));
}

/* The 18 hashed bytes are every field except cfg_hash itself. Laid out
 * explicitly rather than memcpy'd off the struct, so that the hash the node
 * computes cannot drift with compiler padding decisions. */
uint16_t subnet_cfg_hash(const cfg_t *cfg)
{
    uint8_t body[18];
    wr16(body +  0, cfg->cfg_version);
    wr16(body +  2, cfg->sample_interval_s);
    wr16(body +  4, cfg->wor_period_ms);
    body[6] = cfg->tx_power_dbm;
    wr16(body +  7, cfg->tilt_alert_mdeg);
    wr16(body +  9, cfg->vib_alert_mg);
    wr16(body + 11, cfg->tilt_rate_alert_mdeg_h);
    wr16(body + 13, (uint16_t)cfg->tilt_offset_pitch);
    wr16(body + 15, (uint16_t)cfg->tilt_offset_roll);
    body[17] = cfg->flags;
    return mesh_crc16(body, sizeof(body));
}

bool subnet_cfg_valid(const cfg_t *cfg)
{
    return cfg->cfg_hash == subnet_cfg_hash(cfg);
}
