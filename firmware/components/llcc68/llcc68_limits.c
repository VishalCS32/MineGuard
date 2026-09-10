/*
 * The LLCC68's spreading-factor limits, kept free of ESP-IDF so the host tests
 * can pin them.
 *
 * This is not a formality. The LLCC68 is the cost-reduced sibling of the SX1262
 * and its SF range is genuinely narrower, which is easy to miss when every LoRa
 * tutorial on the internet is written for an SX1262 or an SX1276 and reaches
 * for SF12 the moment range disappoints. On this chip SF12 does not exist, and
 * at 125 kHz anything above SF9 does not exist either.
 */
#include <stdbool.h>
#include <stdint.h>

#include "llcc68_limits.h"

bool llcc68_check_sf_bw(uint8_t sf, uint8_t bw)
{
    if (sf < 5) return false;
    switch (bw) {
    case LLCC68_BW_125: return sf <= 9;
    case LLCC68_BW_250: return sf <= 10;
    case LLCC68_BW_500: return sf <= 11;
    default:            return false;
    }
}
