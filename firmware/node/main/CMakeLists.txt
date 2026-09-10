idf_component_register(
    SRCS         "main.c"
    INCLUDE_DIRS "." "${CMAKE_CURRENT_LIST_DIR}/../../common"
    REQUIRES     subnet_proto meshnet nodecfg nodelogic
                 llcc68 lis3dh gnss battery
                 driver esp_adc esp_timer esp_hw_support nvs_flash
)
