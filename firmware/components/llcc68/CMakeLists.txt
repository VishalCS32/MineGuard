idf_component_register(
    SRCS        "llcc68.c" "llcc68_limits.c"
    INCLUDE_DIRS "include"
    REQUIRES     driver esp_timer
)
