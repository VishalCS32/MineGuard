# SUBSIDENCE-NET gateway -- ESP32-S3, the same board as a node.
#
#   idf.py set-target esp32s3
#   idf.py build flash monitor
#
# What makes this board a gateway rather than a node is the modules on its
# headers and `set role gateway` in NVS, not the silicon.
cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../components")
set(COMPONENTS main)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(subnet_gateway)
