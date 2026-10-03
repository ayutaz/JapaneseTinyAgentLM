# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import pytest

from jtalm.data.checks import device_evidence


def c(name: str, **arguments: object) -> dict:
    return {"name": name, "arguments": arguments}


LED = c("set_led", color="blue")
VOL = c("set_volume", level=50)
UP = c("adjust_volume", direction="up", amount="normal")
BRIGHT = c("set_brightness", level=80)
DIM = c("adjust_brightness", direction="down", amount="normal")


@pytest.mark.parametrize(
    ("text", "calls"),
    [
        ("LEDを青に", [LED]),
        ("ＬＥＤを青に", [LED]),
        ("led off", [LED]),
        ("Ledを青に", [LED]),
        ("ライトを消して", [LED]),
        ("ランプを青に", [LED]),
        ("音量を上げて", [UP]),
        ("ボリューム50", [VOL]),
        ("ミュートして", [VOL]),
        ("消音にして", [VOL]),
        ("静かにして", [VOL]),
        ("しずかにして", [VOL]),
        ("うるさいよ", [VOL]),
        ("音を大きくして", [UP]),
        ("音を下げて", [UP]),
        ("声を小さくして", [UP]),
        ("画面を暗くして", [DIM]),
        ("明るさ80", [BRIGHT]),
        ("LEDを青にして音量を50に", [LED, VOL]),
        ("こんにちは", [c("look", direction="left", amount="normal")]),  # not a device call
        ("こんにちは", []),
    ],
)
def test_device_evidence_accepts(text: str, calls: list) -> None:
    assert device_evidence(text, calls) == []


@pytest.mark.parametrize(
    ("text", "calls", "missing"),
    [
        ("音楽、かけてくれる?", [VOL], ["set_volume"]),
        ("音楽を大きくして", [UP], ["adjust_volume"]),
        ("変な音がする", [VOL], ["set_volume"]),
        ("大きな声で話して", [UP], ["adjust_volume"]),
        ("上げて", [UP], ["adjust_volume"]),
        (
            "部屋を明るくして",
            [c("adjust_brightness", direction="up", amount="normal")],
            ["adjust_brightness"],
        ),
        ("暗くして", [DIM], ["adjust_brightness"]),
        ("まぶしい", [BRIGHT], ["set_brightness"]),
        ("光って", [LED], ["set_led"]),
        ("点灯して", [LED], ["set_led"]),
        ("消灯して", [LED], ["set_led"]),
        ("にっこりして", [c("set_expression", expression="happy"), LED], ["set_led"]),
        ("音量を上げて", [UP, LED, DIM], ["set_led", "adjust_brightness"]),
    ],
)
def test_device_evidence_rejects(text: str, calls: list, missing: list) -> None:
    assert device_evidence(text, calls) == missing
