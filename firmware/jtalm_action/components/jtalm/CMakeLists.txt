# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
#
# The LM runtime, compiled straight from runtime/host (not copied), so the device runs exactly
# the code that was checked against PyTorch on the host. Other projects can depend on
# runtime/host directly through the component manager (runtime/host/README.md).
include("${CMAKE_CURRENT_LIST_DIR}/../../../../runtime/host/CMakeLists.txt")
