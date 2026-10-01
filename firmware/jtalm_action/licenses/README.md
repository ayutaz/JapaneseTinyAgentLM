# Third-party notices for the jtalm_action firmware binary

The firmware image (`stackchan_k151_jtalm_action.bin`) is built from the JapaneseTinyAgentLM firmware
(Apache-2.0) with ESP-IDF v5.5.5 and links the following third-party code. Their license texts
are in this folder.

| Component | Used for | License | File |
|---|---|---|---|
| ESP-IDF v5.5.5 (Espressif Systems) | bootloader, drivers, startup | Apache-2.0 | `ESP-IDF_LICENSE.txt` |
| Third-party parts of ESP-IDF (summary by Espressif) | | various | `ESP-IDF_COPYRIGHT.rst` |
| newlib (C library, via ESP-IDF) | C runtime | BSD-style, various | `newlib_COPYING.NEWLIB` |
| FreeRTOS kernel (via ESP-IDF) | tasks | MIT | `FreeRTOS_LICENSE.md` |
| M5Unified 0.2.17 (M5Stack) | display, touch, power | MIT | `M5Unified_LICENSE.txt` |
| M5GFX 0.2.23 (M5Stack) | drawing the face | MIT | `M5GFX_LICENSE.txt` |
| GLCD font from Adafruit GFX (bundled in M5GFX) | default font of M5GFX | BSD-2-Clause | `Adafruit_GFX_LICENSE.txt` |

The model data written at 0x200000 is the JapaneseTinyAgentLM Action 3M model (CC BY-SA 4.0).
