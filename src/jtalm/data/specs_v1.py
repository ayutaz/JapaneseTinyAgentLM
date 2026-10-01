# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Label-first specs for Action schema v1 data (data v1.0, eval v3, the Stack-chan paraphrases).

Data v1.0 keeps the v0.5.1 sentences (re-verified under schema v1, jtalm.data.build_v1) and adds
sentences for the new tools and arguments. As in v0 (jtalm.data.specs) a spec fixes the label;
writers only write sentences, and Qwen3 keeps a sentence only if its parse equals the label.
Numbers are asked for in several notations so that 45, ４５ and 四十五 all map to 45.
"""

import itertools
import random

from jtalm.action.schema import TURN_DIRECTIONS, Call
from jtalm.data.specs import EXPR_DESC, Spec

DIR_JA = {"left": "左", "right": "右", "up": "上", "down": "下", "up_left": "左上",
          "up_right": "右上", "down_left": "左下", "down_right": "右下"}  # fmt: skip
AMOUNT_JA = {"slight": "少しだけ", "normal": "", "large": "大きく"}
EXPR_JA = {**EXPR_DESC, "angry": "怒った表情にする", "sleepy": "眠そうな表情にする",
           "doubt": "不思議そうな（困ったような）表情にする"}  # fmt: skip
COLOR_JA = {"red": "赤", "orange": "オレンジ", "yellow": "黄色", "green": "緑",
            "light_blue": "水色", "blue": "青", "purple": "紫", "pink": "ピンク",
            "white": "白"}  # fmt: skip
NUMBER_STYLES = ("算用数字（例: 45）で書く", "漢数字（例: 四十五）で書く",
                 "全角の数字（例: ４５）で書く")  # fmt: skip
LEVEL_STYLES = (*NUMBER_STYLES, "「%」か「パーセント」を付けて書く")
DEGREE_VALUES = (5, 10, 15, 20, 25, 30, 40, 45, 50, 60, 70, 80, 90, 100, 120, 135, 150, 180)
MAX_VERTICAL_DEGREES = 90  # up / down / diagonals: look degrees stay within this
TURN_DEGREE_VALUES = (5, 10, 15, 20, 30, 45, 90)
LEVEL_VALUES = (0, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100)
BY_VALUES = (5, 10, 15, 20, 25, 30, 50)
CONFUSER_TOPICS = {
    "other_devices.lighting": (
        "部屋の照明や電気、寝室のライト、スタンドなど、ロボット以外の照明の操作の依頼"
        "（部屋のライトをつける、明かりを暗くする、など）"
    ),
    "other_devices.climate": (
        "エアコン、暖房、扇風機、加湿器など、ロボット以外の機器の温度や風の操作の依頼"
    ),
    "other_devices.audio_video": (
        "テレビ、スマホ、ステレオ、パソコンなど、ロボット以外の機器の音量や画面の操作の依頼"
    ),
    "numbers_not_actions.temperature": (
        "数字や「度」「%」が入っているが、ロボットの動作の依頼ではない文（気温、室温、体温、"
        "湿度、天気の話など）"
    ),
    "numbers_not_actions.time": (
        "数字が入っているが、ロボットの動作の依頼ではない文（時刻、日付、タイマー、"
        "待ち合わせや予定の話など）"
    ),
    "numbers_not_actions.counting": (
        "数字や「度」「%」が入っているが、ロボットの動作の依頼ではない文（計算、値段、確率、"
        "点数、人数、割合の話など）"
    ),
    "direction_not_command.placement": (
        "左右や上下などの方向の言葉が入っているが、ロボットへの依頼ではない文（物を置いた場所、"
        "家具や物の位置の話など）"
    ),
    "direction_not_command.route": (
        "左右や上下などの方向の言葉が入っているが、ロボットへの依頼ではない文（道案内、"
        "電車や車の進む方向、人への指示の話など）"
    ),
    "assistant_tasks.info": (
        "時刻、天気、ニュース、調べものなど、情報を答えてもらう依頼や質問"
        "（このロボットにはできない依頼）"
    ),
    "assistant_tasks.schedule": (
        "タイマー、アラーム、メモ、予定の登録など、ロボットにはできない依頼"
    ),
    "assistant_tasks.entertainment": (
        "音楽の再生、歌、踊り、写真、ゲームなど、このロボットにはできない依頼"
    ),
    "face_or_color_talk.face": (
        "顔や表情についての話だが、ロボットへの依頼ではない文（絵や写真の顔、人の表情の感想など）"
    ),
    "face_or_color_talk.color": (
        "色についての話だが、ロボットへの依頼ではない文（好きな色、服や物の色の話など）"
    ),
    "face_or_color_talk.brightness": (
        "明るさについての話だが、ロボットへの依頼ではない文（部屋が暗いという感想、"
        "外が明るいという話など）"
    ),
}


def look(direction: str, amount: str | None = None, degrees: int | None = None) -> Call:
    args: dict = {"direction": direction}
    args.update({"degrees": degrees} if degrees is not None else {"amount": amount or "normal"})
    return {"name": "look", "arguments": args}


def turn(direction: str, amount: str | None = None, degrees: int | None = None) -> Call:
    return {**look(direction, amount, degrees), "name": "turn"}


def _count(name: str, n: int) -> Call:
    return {"name": name, "arguments": {"count": n}}


def bow() -> Call:
    return {"name": "bow", "arguments": {}}


def expression(value: str) -> Call:
    return {"name": "set_expression", "arguments": {"expression": value}}


def led(color: str) -> Call:
    return {"name": "set_led", "arguments": {"color": color}}


def level(target: str, value: int) -> Call:
    return {"name": f"set_{target}", "arguments": {"level": value}}


def adjust(target: str, direction: str, amount: str | None = None, by: int | None = None) -> Call:
    args: dict = {"direction": direction}
    args.update({"by": by} if by is not None else {"amount": amount or "normal"})
    return {"name": f"adjust_{target}", "arguments": args}


TARGET_JA = {"volume": "スピーカーの音量", "brightness": "画面の明るさ"}


def describe(call: Call) -> str:
    """Japanese meaning of one v1 call, used inside generation prompts."""
    name, a = call["name"], call["arguments"]
    if name == "look":
        if a["direction"] == "center":
            return "正面（真ん中）に向き直る"
        if "degrees" in a:
            return f"正面を基準に、{DIR_JA[a['direction']]}へ{a['degrees']}度の向きに首を向ける"
        return f"{AMOUNT_JA[a['amount']]}{DIR_JA[a['direction']]}を向く"
    if name == "turn":
        if "degrees" in a:
            return f"今の向きから、さらに{DIR_JA[a['direction']]}へ{a['degrees']}度首を動かす"
        return f"今の向きから、さらに{AMOUNT_JA[a['amount']]}{DIR_JA[a['direction']]}へ首を動かす"
    if name == "nod":
        return f"{a['count']}回うなずく"
    if name == "shake":
        return f"首を横に{a['count']}回振る（いやいやをする）"
    if name == "bow":
        return "お辞儀をする"
    if name == "set_expression":
        return EXPR_JA[a["expression"]]
    if name == "set_led":
        return (
            "台座のLEDライトを消す"
            if a["color"] == "off"
            else (f"台座のLEDライトの色を{COLOR_JA[a['color']]}にする")
        )
    if name.startswith("set_"):
        target = name.removeprefix("set_")
        if target == "volume" and a["level"] == 0:
            return "スピーカーの音を消す（消音にする）"
        return f"{TARGET_JA[target]}を{a['level']}にする"
    target = name.removeprefix("adjust_")
    up = a["direction"] == "up"
    if "by" in a:  # 「スピーカーの音量を10だけ上げる」「画面の明るさを10だけ下げる」
        return f"{TARGET_JA[target]}を{a['by']}だけ{'上げる' if up else '下げる'}"
    amount = AMOUNT_JA[a["amount"]]
    if target == "volume":  # 「スピーカーの音量を少しだけ上げる」
        return f"{TARGET_JA[target]}を{amount}{'上げる' if up else '下げる'}"
    return f"画面を{amount}{'明るくする' if up else '暗くする'}"  # 「画面を少しだけ暗くする」


def _id(call: Call) -> str:
    return ".".join([call["name"], *(str(v) for v in call["arguments"].values())])


def _single(call: Call, hint: str = "", tag: str = "") -> Spec:
    detail = _id(call) + (f".{tag}" if tag else "")
    meaning = f"ロボットに「{describe(call)}」ように頼む"
    return Spec(f"v1.single.{detail}", "single", (call,), meaning, hint)


def single_specs(rng: random.Random) -> list[Spec]:
    specs: list[Spec] = []
    for d in ("up_left", "up_right", "down_left", "down_right"):
        specs += [_single(look(d, a)) for a in AMOUNT_JA]
    for d in TURN_DIRECTIONS:
        cap = 180 if d in ("left", "right") else MAX_VERTICAL_DEGREES
        values = [n for n in DEGREE_VALUES if n <= cap]
        extra = rng.sample([n for n in range(1, cap + 1) if n not in DEGREE_VALUES], 3)
        for i, n in enumerate((*values, *extra)):
            specs.append(_single(look(d, degrees=n), NUMBER_STYLES[i % 3], f"s{i % 3}"))
        specs += [_single(turn(d, a)) for a in AMOUNT_JA]
        for i, n in enumerate(TURN_DEGREE_VALUES):
            specs.append(_single(turn(d, degrees=n), NUMBER_STYLES[i % 3], f"s{i % 3}"))
    specs += [_single(_count("nod", n)) for n in (4, 5)]
    specs += [_single(_count("shake", n)) for n in (1, 2, 3, 4, 5)]
    specs += [_single(bow())]
    specs += [_single(expression(e)) for e in ("angry", "sleepy", "doubt")]
    specs += [_single(led(c)) for c in (*COLOR_JA, "off")]
    extra_levels = rng.sample([n for n in range(1, 100) if n not in LEVEL_VALUES], 5)
    for target in ("volume", "brightness"):
        for i, n in enumerate((*LEVEL_VALUES, *extra_levels)):
            free = n in (0, 100)  # 消音 / 最大 phrasings stay free of notation hints
            specs.append(_single(level(target, n), "" if free else LEVEL_STYLES[i % 4],
                                 "" if free else f"s{i % 4}"))  # fmt: skip
        for d in ("up", "down"):
            specs += [_single(adjust(target, d, a)) for a in AMOUNT_JA]
            specs += [_single(adjust(target, d, by=n)) for n in BY_VALUES]
        specs.append(Spec(f"v1.single.out_of_range.{target}", "single", (level(target, 100),),
                          f"ロボットに「{TARGET_JA[target]}を最大より大きい値（例: 150、200%）に"
                          "する」ように頼む", "100 より大きい数字を必ず入れる"))  # fmt: skip
    return specs


MULTI_POOL_V1 = [
    look("right", degrees=45), look("up", degrees=30), turn("left", "slight"), look("center"),
    _count("nod", 2), _count("shake", 1), bow(), expression("angry"), expression("happy"),
    led("blue"), led("off"), level("volume", 50), adjust("volume", "up"),
    level("brightness", 30), adjust("brightness", "down", "slight"),
]  # fmt: skip
_MOVES = ("look", "turn")


def multi_specs() -> list[Spec]:
    specs = []
    for a, b in itertools.permutations(MULTI_POOL_V1, 2):
        if a["name"] in _MOVES and b["name"] in _MOVES and look("center") not in (a, b):
            continue  # two head moves only when one of them returns to center (as in v0)
        meaning = (f"ロボットに、まず「{describe(a)}」、そのあと「{describe(b)}」の順で、"
                   "2つの動作を頼む（順序が分かるように）")  # fmt: skip
        specs.append(Spec(f"v1.multi.{_id(a)}+{_id(b)}", "multi_action", (a, b), meaning))
    return specs


def _call_pool() -> list[Call]:
    """Distinct calls of the single specs, in a fixed order."""
    seen: dict[str, Call] = {}
    for sp in single_specs(random.Random(20261004)):
        seen.setdefault(_id(sp.label[0]), sp.label[0])
    return list(seen.values())


def _spread(pool: list[Call], k: int, rng: random.Random, skip: set[str]) -> list[Call]:
    """Up to k calls from pool, round-robin over tools so that no tool dominates."""
    groups: dict[str, list[Call]] = {}
    for c in pool:
        if _id(c) not in skip:
            groups.setdefault(c["name"], []).append(c)
    for g in groups.values():
        rng.shuffle(g)
    picked: list[Call] = []
    while len(picked) < k and any(groups.values()):
        for g in groups.values():
            if g and len(picked) < k:
                picked.append(g.pop())
    return picked


NEGATABLE_V1 = [
    turn("right", "slight"), look("right", degrees=45), _count("shake", 1), bow(),
    expression("angry"), expression("sleepy"), expression("doubt"), led("red"), led("off"),
    level("volume", 0), adjust("volume", "up"), adjust("brightness", "down"),
    level("brightness", 100),
]  # fmt: skip
NEGATABLE_V1 += _spread(_call_pool(), 27, random.Random(20261005), {_id(c) for c in NEGATABLE_V1})


def negation_specs() -> list[Spec]:
    return [
        Spec(
            f"v1.negation.{_id(c)}",
            "negation",
            (),
            f"ロボットに「{describe(c)}」ことを、しないように頼む（否定の依頼）",
        )  # fmt: skip
        for c in NEGATABLE_V1
    ]


CORRECTIONS_V1 = [
    (led("red"), led("blue")),
    (led("blue"), led("off")),
    (level("volume", 50), level("volume", 30)),
    (look("right", degrees=30), look("right", degrees=45)),
    (adjust("volume", "up"), adjust("volume", "down")),
    (_count("nod", 1), _count("shake", 1)),
    (expression("happy"), expression("angry")),
    (look("left", "normal"), turn("left", "slight")),
]


def _more_corrections(k: int, rng: random.Random) -> list[tuple[Call, Call]]:
    pool = _call_pool()
    have = {(_id(w), _id(r)) for w, r in CORRECTIONS_V1}
    pairs: list[tuple[Call, Call]] = []
    for right in _spread(pool, k * 2, rng, set()):
        same = [c for c in pool if c["name"] == right["name"] and _id(c) != _id(right)]
        wrong = rng.choice(same or [c for c in pool if _id(c) != _id(right)])
        if (_id(wrong), _id(right)) not in have and len(pairs) < k:
            have.add((_id(wrong), _id(right)))
            pairs.append((wrong, right))
    return pairs


CORRECTIONS_V1 += _more_corrections(14, random.Random(20261006))


def correction_specs() -> list[Spec]:
    specs = [
        Spec(
            f"v1.correction.{_id(w)}->{_id(r)}",
            "correction",
            (r,),
            f"「{describe(w)}」ではなく「{describe(r)}」ように頼む（言い直しや訂正）",
        )  # fmt: skip
        for w, r in CORRECTIONS_V1
    ]
    for neg, pos in [(led("red"), _count("nod", 1)), (level("volume", 80), expression("happy")),
                     (_count("shake", 1), bow())]:  # fmt: skip
        specs.append(
            Spec(
                f"v1.correction.partial.{_id(neg)}->{_id(pos)}",
                "correction",
                (pos,),
                f"「{describe(neg)}」ことはしないで、「{describe(pos)}」ことだけを頼む",
            )
        )
    return specs


def no_action_specs() -> list[Spec]:
    return [Spec(f"v1.no_action.{k}", "no_action", (), f"ロボットに対する、{v}")
            for k, v in CONFUSER_TOPICS.items()]  # fmt: skip


def all_specs_v1(seed: int = 20261002) -> list[Spec]:
    rng = random.Random(seed)
    return (single_specs(rng) + multi_specs() + negation_specs() + correction_specs()
            + no_action_specs())  # fmt: skip


def paraphrase_specs(seed: int = 20261003) -> list[Spec]:
    """Head moves with numbers and amounts, for the paraphrases of the Stack-chan set."""
    rng = random.Random(seed)
    return [s for s in single_specs(rng) if s.label[0]["name"] in _MOVES]
