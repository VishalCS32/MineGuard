idf_component_register(
    SRCS         "main.c" "spool.c" "uplink.c" "webui.c" "fieldview.c" "report.c"
    INCLUDE_DIRS "." "${CMAKE_CURRENT_LIST_DIR}/../../common"
    # The on-site web UI is one HTML file linked straight into the binary. No
    # filesystem to mount, nothing to go missing, and it is served whether or
    # not the SD card is fitted.
    EMBED_TXTFILES "web/index.html"
    REQUIRES     subnet_proto meshnet nodecfg gwrules llcc68 sim800l battery statusled
                 driver esp_adc esp_timer esp_wifi esp_netif esp_event
                 esp_http_client esp_http_server esp-tls mqtt lwip json mbedtls
                 fatfs sdmmc nvs_flash
)
