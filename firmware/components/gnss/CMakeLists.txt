idf_component_register(
    SRCS        "gnss.c" "gnss_nmea.c"
    INCLUDE_DIRS "include"
    REQUIRES     driver esp_timer subnet_proto
)
