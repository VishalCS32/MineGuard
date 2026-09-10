idf_component_register(
    SRCS        "nodecfg.c" "cli.c"
    INCLUDE_DIRS "include"
    REQUIRES     subnet_proto nvs_flash esp_system driver
)
