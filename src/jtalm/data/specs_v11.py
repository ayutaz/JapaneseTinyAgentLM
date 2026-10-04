# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Label-first specs for the data v1.1 top-up: turning the LED on, and LED colours.

Data v1.0 taught a colourless 「ライトをつけて」 as set_led white in only 2 rows. The rows that
mention turning a light on were mostly other devices ([]) or corrections that end in off
(「LEDをつけるんじゃなく、消灯してね」). As a result the v1.0 model answered 「LEDつけて」 and
「LEDを点灯して」 with off, and 「ライトをオンにして」 with orange. Also, set_led rows were mostly
blue or off (the colours of MULTI_POOL_V1), so other colours with 「光って」 fell below the gate.

The specs below add: the LED turned on without a colour (-> white, the rule of
prompts.VERIFY_SYSTEM), every colour with 光る / 点灯 / つける, off with 消す / オフ, these in
two-action requests, negations and corrections, and other lights turned on as no-action.
"""

import itertools

from jtalm.action.schema import Call
from jtalm.data.specs import Spec
from jtalm.data.specs_v1 import COLOR_JA, _count, _id, bow, describe, expression, led, level, look

ON = led("white")  # a colourless "turn the LED on" is white (prompts.VERIFY_SYSTEM)
ON_JA = "台座のLEDライトをつける（色は言わない）"
NO_COLOR = "色の名前（白も）は入れない"
ON_VERBS = {
    "tsukeru": "「つけて」「点けて」「つけてほしい」のような言い方を使う",
    "tento": "「点灯して」「点灯させて」のような言い方を使う",
    "on": "「オンにして」「ONにして」のような言い方を使う",
    "hikaru": "「光らせて」「光って」「ピカッと光って」のような言い方を使う",
}
ON_SHORT = (
    "「LEDつけて」「ライトオン」「ライト点灯」のような、短い言い方や名詞で終わる言い方にする。"
    "「LED」「ライト」「内蔵ライト」「光」のどれかを使い、色の名前（白も）は入れない。"
    "部屋の照明や電気の話にはしない"
)
ON_WEIGHT = 2  # the on specs are listed twice, so about half of the single sentences turn it on
COLOR_VERBS = (
    "色の名前と一緒に「光って」「光らせて」「点灯して」「つけて」のどれかを使う"
    "（例: 赤く光って、青のライトをつけて）"
)
OFF_VERBS = "「消して」「オフにして」「消灯して」「切って」のような言い方を使う"
MULTI_OTHERS = [_count("nod", 1), look("right"), look("center"), bow(), expression("happy"),
                level("volume", 50)]  # fmt: skip
CONFUSER_TOPICS_V11 = {
    "other_lights_on": (
        "部屋の照明や電気、スタンドライト、リビングや寝室のライト、懐中電灯、車のライトなど、"
        "ロボット以外の明かりを「つける」「点灯する」「オンにする」依頼（台座のLEDの話にはしない）"
    ),
    "light_state_talk": (
        "ライトや明かりが「ついている」「ついていない」「まぶしい」という様子や感想の文で、"
        "ロボットへの依頼ではないもの"
    ),
}


def describe_v11(call: Call) -> str:
    return ON_JA if call == ON else describe(call)


def _single(call: Call, tag: str, meaning: str, hint: str, hint_only: bool = False) -> Spec:
    return Spec(f"v11.single.{_id(call)}.{tag}", "single", (call,),
                f"ロボットに「{meaning}」ように頼む", hint, hint_only)  # fmt: skip


def single_specs() -> list[Spec]:
    on = [_single(ON, f"on_{k}", ON_JA, f"{v}。{NO_COLOR}") for k, v in ON_VERBS.items()]
    on.append(_single(ON, "on_short", ON_JA, ON_SHORT, hint_only=True))
    colors = [_single(led(c), "verb", describe(led(c)), COLOR_VERBS) for c in COLOR_JA]
    off = [_single(led("off"), "verb", describe(led("off")), OFF_VERBS)]
    return on * ON_WEIGHT + colors + off


def multi_specs() -> list[Spec]:
    leds = [ON, *(led(c) for c in COLOR_JA if c not in ("blue", "white"))]
    specs = []
    for x, other in itertools.product(leds, MULTI_OTHERS):
        for a, b in ((x, other), (other, x)):
            meaning = (
                f"ロボットに、まず「{describe_v11(a)}」、そのあと「{describe_v11(b)}」の順で、"
                "2つの動作を頼む（順序が分かるように）"
            )
            hint = NO_COLOR if x == ON else ""
            specs.append(Spec(f"v11.multi.{_tag(a)}+{_tag(b)}", "multi_action", (a, b), meaning,
                              hint))  # fmt: skip
    return specs


def _tag(call: Call) -> str:
    return "set_led.on" if call == ON else _id(call)


def negation_specs() -> list[Spec]:
    meaning = f"ロボットに「{ON_JA}」ことを、しないように頼む（否定の依頼）"
    return [Spec("v11.negation.set_led.on", "negation", (), meaning, NO_COLOR)]


CORRECTIONS_V11 = [(led("off"), ON), (ON, led("off")), (ON, led("red")), (led("blue"), ON)]


def correction_specs() -> list[Spec]:
    return [
        Spec(
            f"v11.correction.{_tag(w)}->{_tag(r)}",
            "correction",
            (r,),
            f"「{describe_v11(w)}」ではなく「{describe_v11(r)}」ように頼む（言い直しや訂正）",
        )
        for w, r in CORRECTIONS_V11
    ]


def no_action_specs() -> list[Spec]:
    return [Spec(f"v11.no_action.{k}", "no_action", (), f"ロボットに対する、{v}")
            for k, v in CONFUSER_TOPICS_V11.items()]  # fmt: skip


def all_specs_v11() -> list[Spec]:
    return (single_specs() + multi_specs() + negation_specs() + correction_specs()
            + no_action_specs())  # fmt: skip
