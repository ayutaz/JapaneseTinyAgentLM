# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware" / "tools"))
from stackchan_chat import describe, show  # noqa: E402


def out(*calls: dict) -> str:
    return json.dumps(list(calls), ensure_ascii=False)


@pytest.mark.parametrize(
    ("calls", "text"),
    [
        ((), "何もしない"),
        (({"name": "look", "arguments": {"direction": "right", "degrees": 45}},),
         "右を向く（正面から45°）"),
        (({"name": "look", "arguments": {"direction": "up", "amount": "slight"}},), "少し上を向く"),
        (({"name": "look", "arguments": {"direction": "center", "amount": "normal"}},),
         "正面を向く"),
        (({"name": "turn", "arguments": {"direction": "up_left", "degrees": 10}},),
         "今の向きから左上へ10°"),
        (({"name": "turn", "arguments": {"direction": "right", "amount": "large"}},),
         "今の向きから大きく右へ"),
        (({"name": "nod", "arguments": {"count": 2}},), "2回うなずく"),
        (({"name": "shake", "arguments": {"count": 1}},), "1回首を横に振る"),
        (({"name": "bow", "arguments": {}},), "お辞儀する"),
        (({"name": "set_expression", "arguments": {"expression": "doubt"}},),
         "不思議そうな顔にする"),
        (({"name": "set_led", "arguments": {"color": "light_blue"}},), "LED を水色にする"),
        (({"name": "set_led", "arguments": {"color": "off"}},), "LED を消す"),
        (({"name": "set_volume", "arguments": {"level": 50}},), "音量を50にする"),
        (({"name": "adjust_volume", "arguments": {"direction": "down", "by": 10}},),
         "音量を10下げる"),
        (({"name": "adjust_brightness", "arguments": {"direction": "up", "amount": "slight"}},),
         "画面を少し明るくする"),
        (({"name": "set_led", "arguments": {"color": "blue"}},
          {"name": "set_volume", "arguments": {"level": 0}}),
         "LED を青にする、音量を0にする"),
    ],
)  # fmt: skip
def test_describe(calls: tuple, text: str) -> None:
    assert describe(out(*calls)) == text


def test_describe_keeps_unparsable_output() -> None:
    assert describe("[{") == "[{"


def test_show_setting_records(capsys: pytest.CaptureFixture[str]) -> None:
    # The records servo.c prints, then ones it does not: none may raise in the reader thread.
    show({"t": "setting", "seq": 1, "what": "volume", "level": 50, "ok": 1}, False)
    show({"t": "setting", "seq": 2, "what": "brightness", "level": 5, "ok": 1}, False)
    show({"t": "setting", "seq": 3, "what": "led", "color": "blue", "ok": 1}, False)
    show({"t": "setting", "seq": 4, "what": "led", "color": "off", "ok": 0}, False)
    show({"t": "setting", "seq": 5}, False)
    show({"t": "setting", "what": "speed", "level": 3}, False)
    show({"t": "setting", "seq": 6, "what": "led", "ok": 1}, False)
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "  音量: 50",
        "  画面の明るさ: 5",
        "  LED: 青",
        "  LED: 消灯（失敗）",
        "  ?: ?",
        "  speed: 3",
        "  LED: ?",
    ]
