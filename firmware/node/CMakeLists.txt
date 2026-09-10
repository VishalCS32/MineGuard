# SUBSIDENCE-NET node -- ESP32-S3.
#
#   idf.py set-target esp32s3
#   idf.py build flash monitor
#
# The shared drivers live one level up in firmware/components and are used by
# both applications; only the ones main actually requires get compiled in, so
# the node's binary carries no SIM800L or gateway rule engine.
cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../components")
set(COMPONENTS main)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(subnet_node)
