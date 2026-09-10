#include <string.h>

#include "meshnet.h"

void meshnet_init(meshnet_t *m, uint16_t self_addr, bool relay_enabled)
{
    memset(m, 0, sizeof(*m));
    m->self_addr     = self_addr;
    m->relay_enabled = relay_enabled;
}

uint16_t meshnet_next_seq(meshnet_t *m)
{
    return ++m->tx_seq;
}

static inline bool expired(const meshnet_seen_t *s, uint32_t now_ms)
{
    /* Unsigned subtraction, so a millisecond counter that wraps at 49 days does
     * not make every entry look infinitely old. */
    return (uint32_t)(now_ms - s->at_ms) > MESHNET_SEEN_TTL_MS;
}

bool meshnet_mark_seen(meshnet_t *m, uint16_t src, uint16_t seq, uint32_t now_ms)
{
    int free_slot = -1, oldest = 0;
    uint32_t oldest_age = 0;

    for (int i = 0; i < MESHNET_SEEN_SLOTS; i++) {
        meshnet_seen_t *s = &m->seen[i];
        if (!s->used) { if (free_slot < 0) free_slot = i; continue; }
        if (s->src == src && s->seq == seq && !expired(s, now_ms)) {
            s->at_ms = now_ms;      /* refresh: the flood is still echoing */
            return false;
        }
        if (expired(s, now_ms)) { s->used = false; if (free_slot < 0) free_slot = i; continue; }
        uint32_t age = (uint32_t)(now_ms - s->at_ms);
        if (age >= oldest_age) { oldest_age = age; oldest = i; }
    }

    int slot = (free_slot >= 0) ? free_slot : oldest;
    m->seen[slot] = (meshnet_seen_t){ .src = src, .seq = seq, .at_ms = now_ms, .used = true };
    return true;
}

meshnet_action_t meshnet_on_rx(meshnet_t *m, const subnet_frame_t *f, uint32_t now_ms)
{
    m->rx_total++;

    /* Our own frame, flooded back to us. Not an error, just done travelling. */
    if (f->src == m->self_addr) { m->rx_dup++; return MESHNET_DROP; }

    if (!meshnet_mark_seen(m, f->src, f->seq, now_ms)) {
        m->rx_dup++;
        return MESHNET_DROP;
    }

    bool for_us     = (f->dst == m->self_addr);
    bool broadcast  = (f->dst == ADDR_BROADCAST);
    bool can_relay  = m->relay_enabled && f->ttl > 1;

    if (for_us)    return MESHNET_CONSUME;
    if (broadcast) return can_relay ? MESHNET_CONSUME_AND_RELAY : MESHNET_CONSUME;

    if (!m->relay_enabled) return MESHNET_DROP;
    if (f->ttl <= 1) { m->dropped_ttl++; return MESHNET_DROP; }

    m->relayed++;
    return MESHNET_RELAY;
}

bool meshnet_prepare_relay(uint8_t *buf, uint16_t len, const subnet_frame_t *f)
{
    if (f->ttl <= 1) return false;
    uint8_t hops = (f->hops < 255) ? (uint8_t)(f->hops + 1) : 255;
    subnet_frame_rehop(buf, len, (uint8_t)(f->ttl - 1), hops);
    return true;
}

void meshnet_note_neighbor(meshnet_t *m, uint16_t addr, int8_t rssi, uint8_t snr,
                           uint32_t now_ms)
{
    if (addr == ADDR_BROADCAST || addr == ADDR_UNASSIGNED) return;

    int slot = -1, weakest = 0;
    int8_t weakest_rssi = 127;

    for (int i = 0; i < MESH_MAX_NEIGHBORS; i++) {
        meshnet_neighbor_t *n = &m->neighbors[i];
        if (n->addr == addr) { slot = i; break; }
        if (n->addr == ADDR_UNASSIGNED) { if (slot < 0) slot = i; continue; }
        if (n->rssi <= weakest_rssi) { weakest_rssi = n->rssi; weakest = i; }
    }
    /* Table full of stronger links: keep those. Reporting the eight best links
     * describes the topology; reporting the eight most recent describes noise. */
    if (slot < 0) {
        if (rssi <= weakest_rssi) return;
        slot = weakest;
    }
    m->neighbors[slot] = (meshnet_neighbor_t){
        .addr = addr, .rssi = rssi, .snr = snr, .at_ms = now_ms };
}

uint16_t meshnet_build_neighbor_payload(const meshnet_t *m, uint32_t t_epoch,
                                        uint8_t *out, uint16_t out_cap,
                                        uint32_t now_ms, uint32_t max_age_ms)
{
    if (out_cap < sizeof(neigh_hdr_t)) return 0;

    uint8_t count = 0;
    uint16_t off = sizeof(neigh_hdr_t);

    for (int i = 0; i < MESH_MAX_NEIGHBORS && count < MESH_MAX_NEIGHBORS; i++) {
        const meshnet_neighbor_t *n = &m->neighbors[i];
        if (n->addr == ADDR_UNASSIGNED) continue;
        if ((uint32_t)(now_ms - n->at_ms) > max_age_ms) continue;
        if (off + sizeof(neigh_entry_t) > out_cap) break;

        neigh_entry_t e = { .addr = n->addr, .rssi = n->rssi, .snr = n->snr };
        memcpy(out + off, &e, sizeof(e));
        off += sizeof(e);
        count++;
    }
    if (count == 0) return 0;

    neigh_hdr_t hdr = { .t_epoch = t_epoch, .count = count };
    memcpy(out, &hdr, sizeof(hdr));
    return off;
}
