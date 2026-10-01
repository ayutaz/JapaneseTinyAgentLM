# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
#
# The runtime as a library: an ESP-IDF component named after the dependency that pulls it in
# (e.g. "jtalm" in idf_component.yml, see README.md), or a static library `jtalm` in a plain
# CMake build. The command-line tool (main.c) is built by the Makefile only.
# Paths are absolute, so this file can also be include()d from a wrapper component.
set(JTLM_DIR "${CMAKE_CURRENT_LIST_DIR}")
set(JTLM_SRCS "${JTLM_DIR}/model.c" "${JTLM_DIR}/tokenizer.c" "${JTLM_DIR}/grammar.c")

if(ESP_PLATFORM)
  idf_component_register(SRCS ${JTLM_SRCS} INCLUDE_DIRS "${JTLM_DIR}")
  # Same numerics as the parity-checked host build with -DJTLM_ACC=float: single-precision
  # accumulators (the S3 FPU has no double), and no fused multiply-add where PyTorch rounds twice.
  target_compile_options(${COMPONENT_LIB} PRIVATE -DJTLM_ACC=float -ffp-contract=off)
  if(CONFIG_JTLM_KV_INT8)
    # PUBLIC: the option changes jtlm_state, so callers must see it too (Kconfig)
    target_compile_definitions(${COMPONENT_LIB} PUBLIC JTLM_KV_INT8=1)
  endif()
else()
  cmake_minimum_required(VERSION 3.16)
  project(jtalm C)
  add_library(jtalm STATIC ${JTLM_SRCS})
  set_target_properties(jtalm PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON)
  target_include_directories(jtalm PUBLIC "${JTLM_DIR}")
  target_compile_options(jtalm PRIVATE -ffp-contract=off)
  target_link_libraries(jtalm PUBLIC m)
endif()
