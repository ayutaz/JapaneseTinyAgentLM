# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 JapaneseTinyAgentLM contributors
#
# The LM runtime is compiled straight from runtime/host (not copied), so the device runs
# exactly the code that was checked against PyTorch on the host.
set(RT "${CMAKE_CURRENT_LIST_DIR}/../../../runtime/host")

idf_component_register(SRCS "main.c" "action.c" "servo.c" "board.cpp"
                            "${RT}/model.c" "${RT}/tokenizer.c" "${RT}/grammar.c"
                       INCLUDE_DIRS "." "${RT}"
                       PRIV_REQUIRES esp_partition esp_psram esp_timer spi_flash mbedtls
                                     esp_driver_usb_serial_jtag esp_driver_uart vfs
                                     esp_app_format M5Unified m5gfx)

# Same numerics as the parity-checked host build with -DJTLM_ACC=float: single-precision
# accumulators, and no fused multiply-add (the S3 FPU has madd.s) where PyTorch rounds twice.
target_compile_options(${COMPONENT_LIB} PRIVATE -DJTLM_ACC=float -ffp-contract=off)
