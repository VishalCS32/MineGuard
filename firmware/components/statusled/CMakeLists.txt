idf_component_register(
    SRCS        "statusled.c" "statusled_pattern.c"
    INCLUDE_DIRS "include"
    REQUIRES     driver esp_timer   # driver brings in esp_driver_rmt on 5.3+
)
