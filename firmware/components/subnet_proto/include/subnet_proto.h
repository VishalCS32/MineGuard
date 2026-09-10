/*
 * Frame assembly and validation, shared by node and gateway.
 *
 * Deliberately free of ESP-IDF: this file and subnet_proto.c compile on the host
 * as well as the target, and host_test/ exercises them against the same vectors
 * the Python codec is checked against. A wire-format bug found on a laptop costs
 * a minute; the same bug found on a hillside costs a field trip.
 */
#ifndef SUBNET_PROTO_H
#define SUBNET_PROTO_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "mesh_proto.h"

#define SUBNET_MAX_FRAME (MESH_HDR_LEN + MESH_MAX_PAYLOAD)

typedef enum {
    SUBNET_OK = 0,
    SUBNET_ERR_SHORT,        /* fewer bytes than a header                    */
    SUBNET_ERR_MAGIC,        /* not one of ours -- noise, or another network */
    SUBNET_ERR_VERSION,      /* a protocol we do not speak                   */
    SUBNET_ERR_CRC,          /* corrupted in flight                          */
    SUBNET_ERR_LENGTH,       /* payload length wrong for the message type    */
    SUBNET_ERR_TOO_BIG,      /* would not fit the radio's payload budget     */
} subnet_err_t;

/* A decoded frame. `payload` points into the caller's buffer -- no copying, and
 * no allocation anywhere in this module. */
typedef struct {
    uint8_t        type;
    uint8_t        version;
    uint16_t       src;
    uint16_t       dst;
    uint16_t       seq;
    uint8_t        ttl;
    uint8_t        hops;
    const uint8_t *payload;
    uint16_t       payload_len;
} subnet_frame_t;

const char *subnet_strerror(subnet_err_t err);

/* Expected payload size for a message type, or 0 when it is variable (NEIGHBOR). */
uint16_t subnet_payload_len(uint8_t msg_type);

/*
 * Build a frame into `out` (at least SUBNET_MAX_FRAME bytes).
 * Returns the total length, or 0 if the payload will not fit.
 */
size_t subnet_frame_build(uint8_t *out, size_t out_cap,
                          uint8_t msg_type, uint16_t src, uint16_t dst,
                          uint16_t seq, uint8_t ttl, uint8_t hops,
                          const void *payload, uint16_t payload_len);

/*
 * Validate and parse. Checks magic, version, CRC and -- for fixed-size types --
 * the payload length, because a frame that decodes into the wrong struct is far
 * more dangerous than one that is rejected.
 */
subnet_err_t subnet_frame_parse(const uint8_t *buf, size_t len, subnet_frame_t *out);

/*
 * Rewrite ttl/hops in place and repair the CRC. Used by a relay: the frame is
 * forwarded unchanged except for the two fields that describe its journey.
 */
void subnet_frame_rehop(uint8_t *buf, size_t len, uint8_t ttl, uint8_t hops);

/* CRC16 over the 18 hashed bytes of a config, matching Config.compute_hash(). */
uint16_t subnet_cfg_hash(const cfg_t *cfg);

/* True when a config's stored hash matches what its fields imply. */
bool subnet_cfg_valid(const cfg_t *cfg);

#endif /* SUBNET_PROTO_H */
