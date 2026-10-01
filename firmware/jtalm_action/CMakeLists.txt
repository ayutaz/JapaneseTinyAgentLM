# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
cmake_minimum_required(VERSION 3.16)

# M5Unified 0.2.17 and M5GFX 0.2.23 (MIT) for the display, touch and power: compiled in place
# from the submodules of the stackchan-idf checkout in firmware/third_party (not in Git; see
# firmware/README.md). Other checkouts of the same versions can be given with
# -DM5UNIFIED_DIR=... -DM5GFX_DIR=... (the M5GFX directory must be named "m5gfx").
set(JTALM_TP "${CMAKE_CURRENT_LIST_DIR}/../third_party/stackchan-idf")
if(NOT DEFINED M5UNIFIED_DIR)
  set(M5UNIFIED_DIR "${JTALM_TP}/components/M5Unified")
endif()
if(NOT DEFINED M5GFX_DIR)
  set(M5GFX_DIR "${JTALM_TP}/third_party/m5gfx")
endif()
set(EXTRA_COMPONENT_DIRS "${M5UNIFIED_DIR}" "${M5GFX_DIR}")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(jtalm_action)
