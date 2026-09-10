#!/usr/bin/env bash
# Compile and run the firmware's portable core on the host.
# No ESP-IDF, no hardware -- just the logic that would otherwise only be
# testable by walking up a hill with 21 boards.
set -euo pipefail
cd "$(dirname "$0")"
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

cc -std=c11 -Wall -Wextra -Werror -O1 \
   -I../common \
   -I../components/subnet_proto/include \
   -I../components/meshnet/include \
   -I../components/llcc68/include \
   -I../components/gnss/include \
   -I../components/nodelogic/include \
   -I../components/gwrules/include \
   -I../components/statusled/include \
   test_firmware.c \
   ../components/subnet_proto/subnet_proto.c \
   ../components/meshnet/meshnet.c \
   ../components/llcc68/llcc68_limits.c \
   ../components/gnss/gnss_nmea.c \
   ../components/nodelogic/nodelogic.c \
   ../components/gwrules/gwrules.c \
   ../components/statusled/statusled_pattern.c \
   -lm \
   -o "$OUT/test_firmware"

"$OUT/test_firmware"
