#ifndef LLCC68_LIMITS_H
#define LLCC68_LIMITS_H

#include <stdbool.h>
#include <stdint.h>

/* Bandwidth codes, as the chip encodes them. */
#define LLCC68_BW_125  0x04
#define LLCC68_BW_250  0x05
#define LLCC68_BW_500  0x06

/*
 * True when the LLCC68 can actually run this spreading factor at this
 * bandwidth:
 *
 *     BW 125 kHz  ->  SF5..SF9      <-- what this system uses, at the ceiling
 *     BW 250 kHz  ->  SF5..SF10
 *     BW 500 kHz  ->  SF5..SF11
 *     SF12        ->  unavailable at any bandwidth
 */
bool llcc68_check_sf_bw(uint8_t sf, uint8_t bw);

#endif /* LLCC68_LIMITS_H */
