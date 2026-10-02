# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import pytest

from jtalm.data.checks import v1_evidence


def c(name: str, **arguments: object) -> dict:
    return {"name": name, "arguments": arguments}


TURN = c("turn", direction="right", amount="slight")
LOOK = c("look", direction="left", amount="normal")


@pytest.mark.parametrize(
    ("text", "calls"),
    [
        ("もう少し右", [TURN]),
        ("さらに右へ", [TURN]),
        ("そこから右に", [TURN]),
        ("あとちょっと右", [TURN]),
        ("続けて右", [TURN]),
        ("右に45度", [c("look", direction="right", degrees=45)]),
        ("右に４５度", [c("look", direction="right", degrees=45)]),
        ("右に九十度", [c("look", direction="right", degrees=90)]),
        ("右へ30°", [c("look", direction="right", degrees=30)]),
        ("もっと右に30度ほど", [c("turn", direction="right", degrees=30)]),
        ("右上を見て", [c("look", direction="up_right", amount="normal")]),
        ("ななめ下", [c("look", direction="down_left", amount="normal")]),
        ("LEDを青に", [c("set_led", color="blue")]),
        ("ＬＥＤを青に", [c("set_led", color="blue")]),
        ("led off", [c("set_led", color="off")]),
        ("ライトを消して", [c("set_led", color="off")]),
        ("音量を上げて", [c("adjust_volume", direction="up", amount="normal")]),
        ("ボリューム50", [c("set_volume", level=50)]),
        ("静かにして", [c("set_volume", level=0)]),
        ("画面を明るくして", [c("adjust_brightness", direction="up", amount="normal")]),
        ("明るさ80", [c("set_brightness", level=80)]),
        ("首を横に振って", [c("shake", count=1)]),
        ("首振って", [c("shake", count=2)]),
        ("イヤイヤして", [c("shake", count=1)]),
        ("お辞儀して", [c("bow")]),
        ("頭を下げて", [c("bow")]),
        ("怒って", [c("set_expression", expression="angry")]),
        ("ぷんぷんして", [c("set_expression", expression="angry")]),
        ("眠そうにして", [c("set_expression", expression="sleepy")]),
        ("首をかしげて", [c("set_expression", expression="doubt")]),
        ("不思議そうな顔", [c("set_expression", expression="doubt")]),
        ("4回うなずいて", [c("nod", count=4)]),
        ("４回うなずいて", [c("nod", count=4)]),
        ("五回うなずいて", [c("nod", count=5)]),
        ("LEDを赤にしてもう少し右", [c("set_led", color="red"), TURN]),
    ],
)
def test_v1_evidence_accepts(text: str, calls: list) -> None:
    assert v1_evidence(text, calls) == []


@pytest.mark.parametrize(
    ("text", "calls", "missing"),
    [
        ("ちょっとだけ左を向いて", [TURN], ["turn"]),
        ("ちょこっと上向いてくれる?", [c("turn", direction="up", amount="slight")], ["turn"]),
        ("右を向いて", [c("look", direction="right", degrees=45)], ["degrees"]),
        ("もう少し右", [c("turn", direction="right", degrees=30)], ["degrees"]),
        ("右を見て", [c("look", direction="up_right", amount="normal")], ["diagonal"]),
        (
            "にっこりして、いい感じにしてね",
            [c("set_expression", expression="happy"), c("set_led", color="pink")],
            ["set_led"],
        ),
        ("笑いはやめて、ちょっと待って", [c("set_led", color="off")], ["set_led"]),
        ("へんてこ下向けないでよ", [c("shake", count=1)], ["shake"]),
        ("上げて", [c("adjust_volume", direction="up", amount="normal")], ["adjust_volume"]),
        ("50にして", [c("set_volume", level=50)], ["set_volume"]),
        (
            "上げて",
            [c("adjust_brightness", direction="up", amount="normal")],
            ["adjust_brightness"],
        ),
        ("よろしく", [c("bow")], ["bow"]),
        ("変な顔して", [c("set_expression", expression="angry")], ["set_expression:angry"]),
        ("変な顔して", [c("set_expression", expression="sleepy")], ["set_expression:sleepy"]),
        ("変な顔して", [c("set_expression", expression="doubt")], ["set_expression:doubt"]),
        ("たくさんうなずいて", [c("nod", count=4)], ["nod:count"]),
        ("5回うなずいて", [c("nod", count=4)], ["nod:count"]),
        (
            "ちょっと右を見て",
            [c("turn", direction="up_right", degrees=20), c("set_led", color="red")],
            ["turn", "degrees", "diagonal", "set_led"],
        ),
    ],
)
def test_v1_evidence_rejects(text: str, calls: list, missing: list) -> None:
    assert v1_evidence(text, calls) == missing


@pytest.mark.parametrize(
    "calls",
    [
        [LOOK],
        [c("look", direction="center", amount="normal")],
        [c("set_expression", expression="happy")],
        [c("nod", count=3)],
        [],
    ],
)
def test_v0_elements_need_no_evidence(calls: list) -> None:
    assert v1_evidence("こんにちは", calls) == []
