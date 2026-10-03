# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
from collections import Counter

from jtalm.action.schema import TOOLS, validate
from jtalm.data import prompts
from jtalm.data.specs_v1 import all_specs_v1, describe, paraphrase_specs


def test_every_spec_label_is_valid_and_ids_are_unique() -> None:
    specs = all_specs_v1()
    assert len({s.id for s in specs}) == len(specs)
    for s in specs:
        assert validate(list(s.label)) == [], s.id
        assert s.meaning


def test_every_tool_appears_in_single_specs() -> None:
    names = {c["name"] for s in all_specs_v1() if s.category == "single" for c in s.label}
    assert names == set(TOOLS)


def test_number_specs_ask_for_each_notation() -> None:
    hints = Counter(s.hint for s in all_specs_v1() if "degrees" in str(s.label))
    assert {h for h in hints if h} >= {"算用数字（例: 45）で書く", "漢数字（例: 四十五）で書く",
                                       "全角の数字（例: ４５）で書く"}  # fmt: skip


def test_out_of_range_specs_are_labeled_with_the_maximum() -> None:
    oor = [s for s in all_specs_v1() if s.id.startswith("v1.single.out_of_range")]
    assert oor and all(s.label[0]["arguments"]["level"] == 100 for s in oor)


def test_describe_and_prompts_cover_v1() -> None:
    assert describe({"name": "turn", "arguments": {"direction": "right", "degrees": 10}}) == (
        "今の向きから、さらに右へ10度首を動かす"
    )
    assert "set_led" in prompts.VERIFY_SYSTEM and "turn" in prompts.VERIFY_SYSTEM
    assert prompts.PROMPT_VERSION == "action-v1.0"
    turn_spec = next(s for s in all_specs_v1() if s.id.startswith("v1.single.turn"))
    reqs = prompts.requirements(turn_spec)
    assert any("今の向き" in r for r in reqs)
    assert all(s.label[0]["name"] in ("look", "turn") for s in paraphrase_specs())


def test_describe_adjust() -> None:
    vol = {"name": "adjust_volume", "arguments": {"direction": "up", "amount": "slight"}}
    assert describe(vol) == "スピーカーの音量を少しだけ上げる"
    dim = {"name": "adjust_brightness", "arguments": {"direction": "down", "amount": "slight"}}
    assert describe(dim) == "画面を少しだけ暗くする"
    by = {"name": "adjust_brightness", "arguments": {"direction": "down", "by": 10}}
    assert describe(by) == "画面の明るさを10だけ下げる"


def test_vertical_look_degrees_are_at_most_90() -> None:
    for s in all_specs_v1():
        call = s.label[0] if s.label else {}
        args = call.get("arguments", {})
        if call.get("name") == "look" and "degrees" in args:
            if args["direction"] not in ("left", "right"):
                assert args["degrees"] <= 90, s.id


def test_turn_amount_requirements_have_no_mou_sukoshi_and_state_the_amount() -> None:
    turns = {a: next(s for s in all_specs_v1() if s.id == f"v1.single.turn.left.{a}")
             for a in ("slight", "normal", "large")}  # fmt: skip
    for spec in turns.values():
        assert not any("もう少し" in r for r in prompts.requirements(spec))
    assert any("少し" in r and "必ず" in r for r in prompts.requirements(turns["slight"]))
    assert any("大きく" in r and "必ず" in r for r in prompts.requirements(turns["large"]))
    assert any("量の言葉は入れない" in r for r in prompts.requirements(turns["normal"]))


def test_level_extremes_have_no_notation_hint() -> None:
    for s in all_specs_v1():
        if (
            s.label
            and s.label[0]["name"] == "set_volume"
            and s.label[0]["arguments"]["level"] in (0, 100)
        ):
            if not s.id.startswith("v1.single.out_of_range"):
                assert s.hint == "", s.id
