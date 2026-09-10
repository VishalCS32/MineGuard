idf_component_register(
    SRCS        "lis3dh.c"
    INCLUDE_DIRS "include"
    # `driver` only: it is the umbrella component on every ESP-IDF 5.x, whereas
    # esp_driver_i2c does not exist before v5.3 and would fail to resolve there.
    REQUIRES     driver
)
