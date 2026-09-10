/*
 * The mesh, minus the radio.
 *
 * Flood de-duplication, TTL handling, the relay decision and the neighbour
 * table -- all pure logic, all host-testable. The radio driver calls into this;
 * this calls into nothing. That separation is what lets the routing behaviour be
 * tested on a laptop instead of on a hillside with 21 boards in a rucksack.
 *
 * Routing is a controlled flood, not a routing table. Over a field this size it
 * costs less airtime than maintaining routes across nodes that are asleep 99% of
 * the time, and it self-heals for free: if a relay dies the flood simply finds
 * another path, and the hop count in the frames reports that it did.
 */
#ifndef MESHNET_H
#define MESHNET_H

#include <stdbool.h>
#include <stdint.h>

#include "subnet_proto.h"

/* Remembering the last N (src,seq) pairs is what stops a flood echoing forever.
 * Sized for a 21-node field: every node can have several frames in flight and
 * still not evict an entry before the flood has died out. */
#define MESHNET_SEEN_SLOTS 64

/* An entry older than this cannot still be circulating, so its slot is free.
 * Also the window after which a sequence number that wrapped is safe to reuse. */
#define MESHNET_SEEN_TTL_MS 30000

typedef struct {
    uint16_t src;
    uint16_t seq;
    uint32_t at_ms;
    bool     used;
} meshnet_seen_t;

typedef struct {
    uint16_t addr;
    int8_t   rssi;
    uint8_t  snr;
    uint32_t at_ms;
} meshnet_neighbor_t;

typedef struct {
    uint16_t self_addr;
    bool     relay_enabled;
    meshnet_seen_t     seen[MESHNET_SEEN_SLOTS];
    meshnet_neighbor_t neighbors[MESH_MAX_NEIGHBORS];
    uint16_t tx_seq;
    /* Counters, surfaced over the CLI. A mesh you cannot observe is a mesh you
     * cannot debug when a node stops arriving. */
    uint32_t rx_total, rx_dup, relayed, dropped_ttl, dropped_bad;
} meshnet_t;

void meshnet_init(meshnet_t *m, uint16_t self_addr, bool relay_enabled);

/* Next sequence number for a locally originated frame. Wraps at 16 bits, which
 * the de-duplication window tolerates because entries age out long before. */
uint16_t meshnet_next_seq(meshnet_t *m);

/* True the first time this (src,seq) is offered, false for every repeat. */
bool meshnet_mark_seen(meshnet_t *m, uint16_t src, uint16_t seq, uint32_t now_ms);

typedef enum {
    MESHNET_DROP = 0,   /* duplicate, expired, or our own frame come back    */
    MESHNET_CONSUME,    /* addressed to us: hand it up the stack             */
    MESHNET_RELAY,      /* not ours: rebroadcast with ttl-1, hops+1          */
    MESHNET_CONSUME_AND_RELAY, /* broadcast: act on it AND pass it on        */
} meshnet_action_t;

/*
 * What to do with a frame that just arrived. Decides de-duplication, TTL and
 * addressing in one place so the node and the gateway cannot disagree about it.
 * On MESHNET_RELAY the caller rewrites the buffer with meshnet_prepare_relay().
 */
meshnet_action_t meshnet_on_rx(meshnet_t *m, const subnet_frame_t *f, uint32_t now_ms);

/* Rewrite a frame for forwarding. False when its TTL is spent. */
bool meshnet_prepare_relay(uint8_t *buf, uint16_t len, const subnet_frame_t *f);

/* Record a heard neighbour; keeps the strongest MESH_MAX_NEIGHBORS. */
void meshnet_note_neighbor(meshnet_t *m, uint16_t addr, int8_t rssi, uint8_t snr,
                           uint32_t now_ms);

/*
 * Serialise the neighbour table into a NEIGHBOR payload. Returns payload bytes
 * written, or 0 when nothing has been heard yet -- an empty report is not worth
 * the airtime.
 */
uint16_t meshnet_build_neighbor_payload(const meshnet_t *m, uint32_t t_epoch,
                                        uint8_t *out, uint16_t out_cap,
                                        uint32_t now_ms, uint32_t max_age_ms);

#endif /* MESHNET_H */
