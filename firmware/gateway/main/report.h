/*
 * One description of the gateway and its field, built once and used twice.
 *
 * The on-site web page and the realtime push endpoint want exactly the same
 * document: what this box is doing, and the last thing heard from every node.
 * Building it in two places would let the two drift, and the drift would show
 * up as a dashboard and a phone disagreeing about the field -- which is the
 * failure this project takes most seriously everywhere else.
 *
 * Values here are DECODED, not raw frames. The base64 frames that go to
 * /api/ingest are the system of record and lose nothing; this is the readable
 * view, for a person on a phone or a third-party endpoint that has no copy of
 * the protocol codec.
 */
#ifndef REPORT_H
#define REPORT_H

#include <stdbool.h>
#include <stdint.h>

#include "cJSON.h"
#include "nodecfg.h"

/* A snapshot of everything the gateway knows about itself. Filled by main,
 * which owns the radio, the spool, the rules and the modem. */
typedef struct {
    uint32_t rx_total, rx_dup, rx_bad, relayed;
    uint32_t spool_depth, spool_shed;
    bool     spool_sd;
    uint32_t posted, post_failures, downlinks;
    uint32_t sms_sent, sms_suppressed;
    bool     modem_ready, modem_registered;
    int      modem_csq;
    bool     radio_up;
    uint32_t tx_count, rx_count, crc_err;
    bool     link_down;
    uint16_t vbat_mv;
} gw_status_t;

typedef void (*gw_status_fn)(gw_status_t *out);

void report_init(nodecfg_t *cfg, gw_status_fn status);

/* Caller owns the returned object and deletes it. */
cJSON *report_status(void);
cJSON *report_nodes(void);

/*
 * The push document: status and nodes in one object, as a malloc'd string the
 * caller frees. This is what goes to the realtime endpoint.
 */
char *report_push_document(void);

#endif /* REPORT_H */
