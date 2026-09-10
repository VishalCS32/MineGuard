#define BOARD_GATEWAY

#include <dirent.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#include "board_pins.h"
#include "driver/sdspi_host.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "esp_vfs_fat.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "sdmmc_cmd.h"

#include "spool.h"

static const char *TAG = "spool";

#define MOUNT_POINT   "/sdcard"
#define SEG_DIR       MOUNT_POINT
#define SEG_MAX_BYTES (256 * 1024)
/* 64 segments of 256 kB is 16 MB, which at 34 bytes a frame is roughly three
 * weeks of a 21-node field reporting every minute. Long enough that an outage
 * is a maintenance problem rather than a data-loss one. */
#define SEG_MAX_COUNT 64

/* The RAM fallback. 512 frames is about 25 minutes of the same field -- enough
 * to ride out a WiFi reconnection, not enough to ride out a night, which is why
 * the card matters and why its absence is logged as loudly as it is. */
#define RAM_SLOTS     512

typedef struct {
    uint8_t len;
    uint8_t data[SUBNET_MAX_FRAME];
} record_t;

static SemaphoreHandle_t s_lock;
static bool     s_sd;
static size_t   s_shed;

/* -- RAM ring -------------------------------------------------------------- */
static record_t s_ram[RAM_SLOTS];
static int      s_head, s_tail, s_count;

/* -- SD segments ----------------------------------------------------------- */
static uint32_t s_read_seg, s_write_seg;
static long     s_read_off;
static size_t   s_sd_count;

static void seg_path(char *out, size_t cap, uint32_t seg)
{
    snprintf(out, cap, SEG_DIR "/sp%05lu.bin", (unsigned long)seg);
}

static void pos_save(void)
{
    FILE *f = fopen(MOUNT_POINT "/spool.pos", "wb");
    if (!f) return;
    fprintf(f, "%lu %ld %lu %lu\n", (unsigned long)s_read_seg, s_read_off,
            (unsigned long)s_write_seg, (unsigned long)s_sd_count);
    fclose(f);
}

static void pos_load(void)
{
    FILE *f = fopen(MOUNT_POINT "/spool.pos", "rb");
    if (!f) return;
    unsigned long rs = 0, ws = 0, cnt = 0;
    long off = 0;
    if (fscanf(f, "%lu %ld %lu %lu", &rs, &off, &ws, &cnt) == 4) {
        s_read_seg = (uint32_t)rs; s_read_off = off;
        s_write_seg = (uint32_t)ws; s_sd_count = cnt;
    }
    fclose(f);
}

esp_err_t spool_init(void)
{
    s_lock = xSemaphoreCreateMutex();

    sdmmc_host_t host = SDSPI_HOST_DEFAULT();
    host.slot = SPI2_HOST;          /* the radio's bus; separate chip selects */
    /* 20 MHz. The card and the LLCC68 share MOSI/MISO/SCK, and a long
     * hand-soldered bus on a gateway box does not reliably clock faster. */
    host.max_freq_khz = 20000;

    sdspi_device_config_t slot = SDSPI_DEVICE_CONFIG_DEFAULT();
    slot.gpio_cs = PIN_SD_CS;
    slot.host_id = SPI2_HOST;

    esp_vfs_fat_sdmmc_mount_config_t mount = {
        .format_if_mount_failed = false,   /* never reformat a card that may
                                              hold an outage's worth of data */
        .max_files = 4,
        .allocation_unit_size = 16 * 1024,
    };
    sdmmc_card_t *card = NULL;
    esp_err_t err = esp_vfs_fat_sdspi_mount(MOUNT_POINT, &host, &slot, &mount, &card);
    if (err == ESP_OK) {
        s_sd = true;
        pos_load();

        /* Believe the directory over the saved position: a power cut between
         * the last append and the last position write leaves the file ahead of
         * the bookmark, and re-uplinking a frame is harmless (ingest upserts)
         * while losing one is not. */
        DIR *d = opendir(SEG_DIR);
        if (d) {
            struct dirent *e;
            uint32_t lo = 0xFFFFFFFFu, hi = 0;
            while ((e = readdir(d)) != NULL) {
                unsigned long seg;
                if (sscanf(e->d_name, "sp%05lu.bin", &seg) == 1) {
                    if (seg < lo) lo = (uint32_t)seg;
                    if (seg > hi) hi = (uint32_t)seg;
                }
            }
            closedir(d);
            if (lo != 0xFFFFFFFFu) {
                if (s_read_seg < lo)  { s_read_seg = lo; s_read_off = 0; }
                if (s_write_seg < hi) s_write_seg = hi;
            }
        }
        ESP_LOGI(TAG, "microSD mounted (%lluMB); queue resumes at segment %lu+%ld",
                 ((uint64_t)card->csd.capacity * card->csd.sector_size) >> 20,
                 (unsigned long)s_read_seg, s_read_off);
        return ESP_OK;
    }

    ESP_LOGW(TAG, "no usable microSD (%s) -- buffering in RAM only. "
                  "Frames held during an outage will NOT survive a reboot.",
             esp_err_to_name(err));
    return ESP_OK;
}

bool   spool_using_sd(void) { return s_sd; }
size_t spool_shed(void)     { return s_shed; }

size_t spool_depth(void)
{
    return s_sd ? s_sd_count : (size_t)s_count;
}

/* -- push ------------------------------------------------------------------- */

static void ram_push(const uint8_t *frame, uint8_t len)
{
    if (s_count == RAM_SLOTS) {
        /* Full: the oldest frame goes. Refusing the new one instead would mean
         * a gateway that stops recording the movement happening right now in
         * order to preserve what happened an hour ago. */
        s_tail = (s_tail + 1) % RAM_SLOTS;
        s_count--;
        s_shed++;
    }
    s_ram[s_head].len = len;
    memcpy(s_ram[s_head].data, frame, len);
    s_head = (s_head + 1) % RAM_SLOTS;
    s_count++;
}

static void sd_push(const uint8_t *frame, uint8_t len)
{
    char path[64];
    seg_path(path, sizeof(path), s_write_seg);

    FILE *f = fopen(path, "ab");
    if (!f) {
        ESP_LOGE(TAG, "cannot append to %s; falling back to RAM", path);
        ram_push(frame, len);
        return;
    }
    fwrite(&len, 1, 1, f);
    fwrite(frame, 1, len, f);
    long size = ftell(f);
    fclose(f);
    s_sd_count++;

    if (size >= SEG_MAX_BYTES) {
        s_write_seg++;
        /* Bounded like the card it lives on: past the segment budget the oldest
         * segment is deleted outright. */
        while (s_write_seg - s_read_seg >= SEG_MAX_COUNT) {
            char old[64];
            seg_path(old, sizeof(old), s_read_seg);
            struct stat st;
            if (stat(old, &st) == 0) {
                remove(old);
                ESP_LOGW(TAG, "queue full: shed segment %lu (%ld bytes of "
                              "backlog)", (unsigned long)s_read_seg, (long)st.st_size);
                s_shed += (size_t)st.st_size / 34;   /* approximate frame count */
            }
            s_read_seg++;
            s_read_off = 0;
        }
        pos_save();
    }
}

bool spool_push(const uint8_t *frame, uint8_t len)
{
    if (!frame || len < MESH_HDR_LEN || len > SUBNET_MAX_FRAME) return false;

    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (s_sd) sd_push(frame, len);
    else      ram_push(frame, len);
    xSemaphoreGive(s_lock);
    return true;
}

/* -- peek / consume --------------------------------------------------------- */

static int sd_peek(spool_batch_t *b)
{
    uint32_t seg = s_read_seg;
    long off = s_read_off;

    while (b->count < SPOOL_BATCH_MAX && seg <= s_write_seg) {
        char path[64];
        seg_path(path, sizeof(path), seg);
        FILE *f = fopen(path, "rb");
        if (!f) { if (seg == s_write_seg) break; seg++; off = 0; continue; }
        fseek(f, off, SEEK_SET);

        while (b->count < SPOOL_BATCH_MAX) {
            uint8_t len = 0;
            if (fread(&len, 1, 1, f) != 1) break;
            if (len < MESH_HDR_LEN || len > SUBNET_MAX_FRAME) break;  /* truncated tail */
            if (fread(b->data[b->count], 1, len, f) != len) break;
            b->len[b->count] = len;
            b->count++;
            off = ftell(f);
        }
        fclose(f);

        if (b->count < SPOOL_BATCH_MAX && seg < s_write_seg) { seg++; off = 0; }
        else break;
    }
    return b->count;
}

int spool_peek(spool_batch_t *b)
{
    memset(b, 0, sizeof(*b));

    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (s_sd) {
        sd_peek(b);
    } else {
        int idx = s_tail;
        while (b->count < SPOOL_BATCH_MAX && b->count < s_count) {
            b->len[b->count] = s_ram[idx].len;
            memcpy(b->data[b->count], s_ram[idx].data, s_ram[idx].len);
            b->count++;
            idx = (idx + 1) % RAM_SLOTS;
        }
    }
    xSemaphoreGive(s_lock);
    return b->count;
}

void spool_consume(int n)
{
    if (n <= 0) return;

    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (!s_sd) {
        if (n > s_count) n = s_count;
        s_tail = (s_tail + n) % RAM_SLOTS;
        s_count -= n;
        xSemaphoreGive(s_lock);
        return;
    }

    /* Walk the same records the batch was read from and move the bookmark past
     * them, deleting a segment once nothing in it is still owed. */
    int remaining = n;
    while (remaining > 0) {
        char path[64];
        seg_path(path, sizeof(path), s_read_seg);
        FILE *f = fopen(path, "rb");
        if (!f) {
            if (s_read_seg >= s_write_seg) break;
            s_read_seg++; s_read_off = 0;
            continue;
        }
        fseek(f, s_read_off, SEEK_SET);
        while (remaining > 0) {
            uint8_t len = 0;
            if (fread(&len, 1, 1, f) != 1) break;
            if (fseek(f, len, SEEK_CUR) != 0) break;
            s_read_off = ftell(f);
            remaining--;
            if (s_sd_count) s_sd_count--;
        }
        long size = ftell(f);
        fseek(f, 0, SEEK_END);
        bool at_end = (size >= ftell(f));
        fclose(f);

        if (at_end && s_read_seg < s_write_seg) {
            remove(path);
            s_read_seg++;
            s_read_off = 0;
        } else {
            break;
        }
    }
    pos_save();
    xSemaphoreGive(s_lock);
}
