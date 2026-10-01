# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Label-first specs for synthetic Action data.

Each ``Spec`` fixes the expected output (the label) by construction. An open-weight LLM only writes
Japanese sentences for the spec; a second model then parses each sentence, and only sentences whose
parse equals the spec's label are kept (docs/data.md).
"""

import itertools
import random
from dataclasses import dataclass

from jtalm.action.schema import Call

LOOK_DESC = {
    "left": "左を向く",
    "right": "右を向く",
    "up": "上を向く",
    "down": "下を向く",
    "center": "正面（真ん中）に向き直る",
}
AMOUNT_DESC = {"slight": "少しだけ", "normal": "", "large": "大きく"}
EXPR_DESC = {
    "happy": "嬉しそうな表情（笑顔）にする",
    "sad": "悲しそうな表情にする",
    "surprised": "驚いた表情にする",
    "neutral": "普通の表情（真顔）に戻す",
}
EXPR_NEGATED = {
    "happy": "笑う（嬉しそうな顔をする）",
    "sad": "悲しそうな顔をする",
    "surprised": "驚いた顔をする",
    "neutral": "真顔になる",
}
NO_ACTION_TOPICS = {
    "chitchat": "天気、食べ物、趣味、今日の出来事などについての雑談",
    "robot_question": "ロボット自身への質問（名前、年齢、好きなもの、何ができるか）",
    "knowledge_question": "一般的な知識を問う質問",
    "user_status": "話し手自身の状態や気持ちの報告（疲れた、お腹がすいた、眠い など）",
    "out_of_tool": (
        "このロボットにはできない依頼（部屋の電気を消す、音楽をかける、歩く、手を振る、"
        "物を取ってくる、アラームをかける など）"
    ),
    "vague": "何をしてほしいのか分からない曖昧な依頼（なんかやって、適当に動いて など）",
    "do_nothing": "何もしないでほしい、そのままでいてほしいという依頼",
    "greeting": "あいさつやお礼",
}


def look(direction: str, amount: str = "normal") -> Call:
    return {"name": "look", "arguments": {"direction": direction, "amount": amount}}


def expression(value: str) -> Call:
    return {"name": "set_expression", "arguments": {"expression": value}}


def nod(count: int) -> Call:
    return {"name": "nod", "arguments": {"count": count}}


def describe(call: Call) -> str:
    """Japanese meaning of one call, used inside generation prompts."""
    name, args = call["name"], call["arguments"]
    if name == "look":
        return AMOUNT_DESC[args["amount"]] + LOOK_DESC[args["direction"]]
    if name == "set_expression":
        return EXPR_DESC[args["expression"]]
    return f"{args['count']}回うなずく"


def describe_negated(call: Call) -> str:
    if call["name"] == "set_expression":
        return EXPR_NEGATED[call["arguments"]["expression"]]
    return describe(call)


@dataclass(frozen=True)
class Spec:
    id: str
    category: str  # single | multi_action | negation | correction | no_action
    label: tuple[Call, ...]
    meaning: str  # Japanese instruction describing what the sentence must ask for
    # Extra instruction for focused data (jtalm.data.focus). With ``hint_only`` the hint replaces
    # the default per-call wording rules (e.g. which amount or negation words to use).
    hint: str = ""
    hint_only: bool = False


def single_calls() -> list[Call]:
    looks = [look(d, a) for d in ("left", "right", "up", "down") for a in AMOUNT_DESC]
    return [*looks, look("center"), *(expression(e) for e in EXPR_DESC), nod(1), nod(2), nod(3)]


def _call_id(call: Call) -> str:
    return ".".join([call["name"], *(str(v) for v in call["arguments"].values())])


def single_specs() -> list[Spec]:
    return [
        Spec(f"single.{_call_id(c)}", "single", (c,), f"ロボットに「{describe(c)}」ように頼む")
        for c in single_calls()
    ]


MULTI_POOL = [
    look("left"),
    look("right"),
    look("up"),
    look("down"),
    look("center"),
    look("right", "slight"),
    look("left", "large"),
    *(expression(e) for e in EXPR_DESC),
    nod(1),
    nod(2),
]


def multi_specs() -> list[Spec]:
    specs = []
    for a, b in itertools.permutations(MULTI_POOL, 2):
        if a["name"] == b["name"] == "look" and "center" not in (
            a["arguments"]["direction"],
            b["arguments"]["direction"],
        ):
            continue  # keep two-look sequences only when one of them returns to center
        meaning = (
            f"ロボットに、まず「{describe(a)}」、そのあと「{describe(b)}」の順で、"
            "2つの動作を頼む（順序が分かるように）"
        )
        specs.append(Spec(f"multi.{_call_id(a)}+{_call_id(b)}", "multi_action", (a, b), meaning))
    return specs


NEGATABLE = [
    *(look(d) for d in LOOK_DESC),
    look("right", "slight"),
    look("left", "slight"),
    look("right", "large"),
    look("left", "large"),
    *(expression(e) for e in EXPR_NEGATED),
    nod(1),
    nod(2),
]
NEGATED_GENERAL = {
    "move_head": "首（頭）を動かす",
    "change_face": "表情を変える",
    "move_or_face": "首を動かしたり、表情を変えたりする",
}
NEGATED_PAIRS = [
    (look("right"), expression("happy")),
    (look("up"), nod(1)),
    (expression("surprised"), look("left")),
]


def negation_specs() -> list[Spec]:
    """Negated requests (label ``[]``); widened in v0.2 to reduce duplicate sentences."""

    def spec(key: str, what: str) -> Spec:
        return Spec(
            f"negation.{key}",
            "negation",
            (),
            f"ロボットに「{what}」ことを、しないように頼む（否定の依頼）",
        )

    specs = [spec(_call_id(c), describe_negated(c)) for c in NEGATABLE]
    specs += [spec(f"general.{k}", v) for k, v in NEGATED_GENERAL.items()]
    specs += [
        spec(
            f"pair.{_call_id(a)}+{_call_id(b)}",
            f"{describe_negated(a)}ことも、{describe_negated(b)}",
        )
        for a, b in NEGATED_PAIRS
    ]
    return specs


def correction_specs() -> list[Spec]:
    specs = []
    dir_pairs = [("right", "left"), ("left", "right"), ("up", "down"), ("down", "up")]
    dir_pairs += [("right", "up"), ("left", "down"), ("up", "right"), ("down", "left")]
    for wrong, right in dir_pairs:
        specs.append(
            Spec(
                f"correction.look.{wrong}->{right}",
                "correction",
                (look(right),),
                f"「{LOOK_DESC[wrong]}」ではなく「{LOOK_DESC[right]}」ように頼む（言い直しや訂正）",
            )
        )
    for wrong, right in [("happy", "surprised"), ("sad", "happy"), ("surprised", "happy")]:
        specs.append(
            Spec(
                f"correction.expr.{wrong}->{right}",
                "correction",
                (expression(right),),
                f"「{EXPR_NEGATED[wrong]}」のではなく「{EXPR_DESC[right]}」ように頼む（言い直しや訂正）",
            )
        )
    partial = [
        (expression("happy"), nod(1)),
        (look("right"), expression("happy")),
        (nod(1), look("up")),
        (look("left"), nod(2)),
        (expression("surprised"), look("down")),
    ]
    for neg, pos in partial:
        specs.append(
            Spec(
                f"correction.partial.{_call_id(neg)}->{_call_id(pos)}",
                "correction",
                (pos,),
                f"「{describe_negated(neg)}」ことはしないで、「{describe(pos)}」ことだけを頼む",
            )
        )
    return specs


def no_action_specs() -> list[Spec]:
    return [
        Spec(f"no_action.{key}", "no_action", (), f"ロボットに対する、{desc}")
        for key, desc in NO_ACTION_TOPICS.items()
    ]


def all_specs() -> list[Spec]:
    return (
        single_specs() + multi_specs() + negation_specs() + correction_specs() + no_action_specs()
    )


def sample_requests(
    specs: list[Spec], quota: dict[str, int], per_request: int, rng: random.Random
) -> list[Spec]:
    """Spread a per-category sentence quota over specs as a list of generation requests."""
    requests: list[Spec] = []
    for category, target in quota.items():
        pool = [s for s in specs if s.category == category]
        n_requests = -(-target // per_request)
        cycle = [pool[i % len(pool)] for i in range(n_requests)]
        rng.shuffle(cycle)
        requests.extend(cycle)
    return requests
