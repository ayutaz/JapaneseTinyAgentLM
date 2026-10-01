#!/bin/sh
# Builds jtalm.js (the C runtime as WebAssembly, embedded in one file) with Emscripten:
#   sh runtime/web/build.sh            (emcc on PATH)
# or in Docker:
#   docker run --rm -v "$PWD":/src -w /src emscripten/emsdk:3.1.62 sh runtime/web/build.sh
set -eu
cd "$(dirname "$0")"
emcc -O2 -std=c11 -Wall -Wextra -ffp-contract=off -DJTLM_ACC=float -I../host \
    ../host/model.c ../host/tokenizer.c ../host/grammar.c web.c \
    -o jtalm.js \
    -sMODULARIZE=1 -sEXPORT_NAME=createJtalm -sSINGLE_FILE=1 -sENVIRONMENT=web,node \
    -sALLOW_MEMORY_GROWTH=1 -sSTACK_SIZE=1048576 \
    -sEXPORTED_FUNCTIONS=_web_init,_web_predict,_malloc,_free \
    -sEXPORTED_RUNTIME_METHODS=cwrap,HEAPU8
