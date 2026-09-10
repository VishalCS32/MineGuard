/*
 * Store and forward.
 *
 * Every frame the gateway hears is written down before anything else is
 * attempted with it. Mine sites lose their backhaul -- that is the normal
 * condition, not the exception -- and telemetry gathered during an outage has to
 * survive to be reconciled afterwards rather than being dropped because a POST
 * failed.
 *
 * Two backings, chosen at boot:
 *
 *   microSD   segment files, so the queue survives a reboot and a power cut,
 *             and is bounded the way an SD card is bounded: when the segment
 *             count is reached the OLDEST segment is deleted. Shedding the
 *             oldest is the right choice for a monitoring system -- recent
 *             movement is what a warning is made of.
 *
 *   RAM ring  the fallback when no card is fitted or the card is unreadable.
 *             Bounded the same way and lost on reboot, which is logged loudly
 *             at boot rather than discovered during an incident review.
 */
#ifndef SPOOL_H
#define SPOOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"
#include "subnet_proto.h"

/* One uplink batch. Matches the backend's `frames` list cap (256) with room to
 * spare, and keeps a single HTTP body under ~6 kB of base64. */
#define SPOOL_BATCH_MAX   64

typedef struct {
    uint8_t  data[SPOOL_BATCH_MAX][SUBNET_MAX_FRAME];
    uint8_t  len[SPOOL_BATCH_MAX];
    int      count;
} spool_batch_t;

/* Mount the card if there is one. Never fails: without a card the gateway falls
 * back to RAM, because a gateway that refuses to start is worse than one that
 * cannot survive a reboot. */
esp_err_t spool_init(void);

bool   spool_using_sd(void);
size_t spool_depth(void);           /* frames waiting to be uplinked */
size_t spool_shed(void);            /* frames dropped because the queue was full */

/* Write one frame down. Returns false only if the frame is malformed. */
bool spool_push(const uint8_t *frame, uint8_t len);

/* Fill `batch` with the oldest frames, without removing them: a batch is only
 * consumed once the backend has acknowledged it. */
int  spool_peek(spool_batch_t *batch);

/* Drop the oldest `n` frames -- called after a successful uplink, never before. */
void spool_consume(int n);

#endif /* SPOOL_H */
