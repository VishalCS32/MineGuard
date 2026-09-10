#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "fieldview.h"

static fieldview_node_t  s_nodes[FIELDVIEW_MAX_NODES];
static int               s_count;
static SemaphoreHandle_t s_lock;

void fieldview_init(void)
{
    memset(s_nodes, 0, sizeof(s_nodes));
    s_count = 0;
    s_lock = xSemaphoreCreateMutex();
}

/* Caller holds the lock. */
static fieldview_node_t *slot_for(uint16_t addr)
{
    for (int i = 0; i < s_count; i++)
        if (s_nodes[i].addr == addr) return &s_nodes[i];

    if (s_count < FIELDVIEW_MAX_NODES) {
        fieldview_node_t *n = &s_nodes[s_count++];
        memset(n, 0, sizeof(*n));
        n->addr = addr;
        return n;
    }

    /* More nodes than slots: replace the one nobody has heard from in longest.
     * A table that refuses new entries once full would hide exactly the node
     * that has just been added to the field. */
    fieldview_node_t *oldest = &s_nodes[0];
    for (int i = 1; i < s_count; i++)
        if (s_nodes[i].last_ms < oldest->last_ms) oldest = &s_nodes[i];
    memset(oldest, 0, sizeof(*oldest));
    oldest->addr = addr;
    return oldest;
}

void fieldview_heard(uint16_t addr, int8_t rssi, uint8_t snr, uint8_t hops,
                     uint32_t now_ms)
{
    if (addr == ADDR_UNASSIGNED || addr == ADDR_BROADCAST) return;

    xSemaphoreTake(s_lock, portMAX_DELAY);
    fieldview_node_t *n = slot_for(addr);
    n->last_ms = now_ms;
    n->rssi = rssi;
    n->snr = snr;
    n->hops = hops;
    n->frames++;
    xSemaphoreGive(s_lock);
}

void fieldview_telemetry(uint16_t addr, const tlm_t *t)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    fieldview_node_t *n = slot_for(addr);
    n->have_tlm     = true;
    n->tlm_epoch    = t->t_epoch;
    n->pitch_mdeg   = t->pitch_mdeg;
    n->roll_mdeg    = t->roll_mdeg;
    n->vib_rms_mg   = t->vib_rms_mg;
    n->temp_c_x100  = t->temp_c_x100;
    n->vbat_mv      = t->vbat_mv;
    n->gnss_status  = t->gnss_status;
    n->flags        = t->flags;
    xSemaphoreGive(s_lock);
}

void fieldview_event(uint16_t addr, const evt_t *e)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    fieldview_node_t *n = slot_for(addr);
    n->last_evt_code  = e->event_code;
    n->last_evt_sev   = e->severity;
    n->last_evt_epoch = e->t_epoch;
    xSemaphoreGive(s_lock);
}

int fieldview_count(void)
{
    return s_count;
}

bool fieldview_get(int index, fieldview_node_t *out)
{
    bool ok = false;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (index >= 0 && index < s_count) {
        *out = s_nodes[index];
        ok = true;
    }
    xSemaphoreGive(s_lock);
    return ok;
}
