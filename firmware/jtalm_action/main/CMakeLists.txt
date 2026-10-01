# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
idf_component_register(SRCS "main.c" "action.c" "servo.c" "board.cpp"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES jtalm esp_partition esp_psram esp_timer spi_flash mbedtls
                                     esp_driver_usb_serial_jtag esp_driver_uart esp_driver_tsens vfs
                                     esp_app_format M5Unified m5gfx)

# As in the runtime: no fused multiply-add, so float code here rounds as it did when the
# outputs were checked on the device.
target_compile_options(${COMPONENT_LIB} PRIVATE -ffp-contract=off)
