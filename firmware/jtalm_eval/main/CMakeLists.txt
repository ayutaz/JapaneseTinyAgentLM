# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
idf_component_register(SRCS "main.c"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_partition esp_psram esp_timer spi_flash
                                     app_update bootloader_support)
