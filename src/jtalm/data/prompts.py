# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Prompts for sentence generation and cross-model label verification (versioned)."""

import json
import random

from jtalm.action.schema import load_schema
from jtalm.data.specs import Spec

PROMPT_VERSION = "action-v1.0"

ROBOT = (
    "首を左右・上下・斜めに動かせて、画面に表情を出せて、"
    "台座のLEDライトの色、スピーカーの音量、画面の明るさを変えられる、小さな卓上ロボット"
)

NO_ACTION_REQ = (
    "首を動かす、表情を変える、うなずく、首を振る、お辞儀、"
    "LEDライト・音量・画面の明るさの変更を、ロボットに頼む文にはしない"
)

STYLES_TRAIN = (
    "丁寧語、くだけた口語、短い命令、少し長めの依頼、子どもっぽい言い方、関西弁などの方言、"
    "句読点なし、ひらがな多め、文末に「〜ね」「〜よ」などを付ける"
)
# v0.3 (train only): a longer list; each request gets a random subset (``pick_styles``) so that
# writers do not converge on the same few phrasings. Question forms and indirect requests were the
# main misses of the M4 models, so they are listed explicitly.
STYLES_TRAIN_V03 = (
    "「〜してくれる?」「〜できる?」のような疑問形の依頼",
    "「〜してほしいな」「〜してもらえると嬉しい」のような遠回しな依頼",
    "「〜しよう」「〜してみよっか」のような誘う言い方",
    "ロボットに名前やあだ名で呼びかけてから頼む言い方",
    "敬語でていねいな依頼",
    "友だち同士のくだけた口語",
    "2〜4語だけの短い命令",
    "理由や状況を一言そえた少し長めの依頼",
    "子どもっぽい言い方",
    "関西弁などの方言",
    "句読点なしで打った文",
    "ひらがなを多めに使った文",
    "カタカナ語を混ぜた言い方",
    "「〜ね」「〜よ」「〜な」などの文末",
    "独り言のようにつぶやく言い方",
)
STYLES_EVAL = (
    "友だちに話すような言い方、目上の人への丁寧な言い方、独り言のような言い方、急いでいる言い方、"
    "少し回りくどい言い方、絵文字や記号なし、ひらがなだけ"
)


def sentence_schema(n: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "sentences": {
                "type": "array",
                "items": {"type": "string", "minLength": 2, "maxLength": 60},
                "minItems": n,
                "maxItems": n,
            }
        },
        "required": ["sentences"],
    }


def requirements(spec: Spec) -> list[str]:
    """Spec-specific constraints so every sentence carries all parts of the label (v0.2)."""
    if spec.hint_only:
        reqs = [spec.hint]
        if spec.category == "no_action":
            reqs.append(NO_ACTION_REQ)
        return reqs
    reqs = _default_requirements(spec)
    if spec.hint:
        reqs.append(spec.hint)
    return reqs


NOTATION_NOTE = "（数字の書き方は下の指定に従う）"
_AMOUNT_REQS = {
    "slight": "「少し」「ちょっと」のように、動きや変化が小さいことが分かる言葉を必ず入れる",
    "large": "「大きく」「思いっきり」のように、動きや変化が大きいことが分かる言葉を必ず入れる",
    "normal": "「少し」「大きく」のような量の言葉は入れない",
}


def _amount_req(amount: str) -> str:
    return _AMOUNT_REQS[amount]


def _default_requirements(spec: Spec) -> list[str]:
    reqs: list[str] = []
    for call in spec.label:
        args = call["arguments"]
        if call["name"] in ("look", "turn", "adjust_volume", "adjust_brightness"):
            if "degrees" not in args and "by" not in args:
                if not (call["name"] == "look" and args["direction"] == "center"):
                    reqs.append(_amount_req(args["amount"]))
        if call["name"] == "look" and "degrees" in args:
            reqs.append(f"角度（{args['degrees']}度）を必ず入れる{NOTATION_NOTE}")
        if call["name"] == "look" and args.get("direction") != "center":
            reqs.append(
                "「もう」「さらに」「もっと」「そこから」のような、今の向きを基準にする言葉は入れない"
            )
        if call["name"] == "turn":
            reqs.append(
                "「もう」「さらに」「もっと」「そこから」のように、"
                "今の向きから動かすことが分かる言葉を必ず入れる"
            )
            if "degrees" in args:
                reqs.append(f"角度（{args['degrees']}度）を必ず入れる{NOTATION_NOTE}")
        if call["name"] == "nod" and args["count"] >= 2:
            reqs.append(f"うなずく回数（{args['count']}回）が分かるようにする")
        if call["name"] == "shake":
            reqs.append(
                "首を横に振る動きだと分かる言い方にする（うなずく動きと取り違えない言い方）"
            )
            if args["count"] >= 2:
                reqs.append(f"首を振る回数（{args['count']}回）が分かるようにする")
        if call["name"] == "set_led":
            reqs.append(
                "「LED」「ライト」「内蔵ライト」「光」のどれかを使う。部屋の照明や電気の話にはしない"
            )
        if call["name"] in ("set_volume", "adjust_volume"):
            reqs.append(
                "「音量」「ボリューム」「音」のどれかを使う。テレビなど、ほかの機器の音の話にはしない"
            )
        if call["name"] in ("set_brightness", "adjust_brightness"):
            reqs.append(
                "「画面」「明るさ」「明るく」「暗く」のどれかを使う。部屋の明るさの話にはしない"
            )
        if call["name"] in ("set_volume", "set_brightness") and args["level"] not in (0, 100):
            reqs.append(f"値（{args['level']}）が分かるように書く{NOTATION_NOTE}")
        if call["name"] in ("adjust_volume", "adjust_brightness") and "by" in args:
            reqs.append(f"変える量（{args['by']}）を必ず入れる")
    if spec.category == "multi_action":
        reqs.append("2つの動作の両方を入れ、どちらを先にするかが分かる言い方にする")
    if spec.category == "negation":
        reqs.append("「〜しないで」「〜しなくていい」「〜はやめて」のような否定の依頼にする")
    if spec.category == "correction":
        reqs.append(
            "取り消す動作と、本当にしてほしい動作の両方を文に入れる"
            "（「〜じゃなくて〜」「やっぱり〜はやめて〜」「〜はしないで、〜して」のような形）"
        )
    if spec.category == "no_action":
        reqs.append(NO_ACTION_REQ)
    return reqs


def pick_styles(rng: random.Random, k: int = 4) -> str:
    return "、".join(rng.sample(STYLES_TRAIN_V03, k))


def generation_messages(spec: Spec, n: int, split: str, styles: str | None = None) -> list[dict]:
    """``styles`` overrides the default style list (v0.3 passes a random subset)."""
    if styles is None:
        styles = STYLES_TRAIN if split == "train" else STYLES_EVAL
    extra = "".join(f"- {r}\n" for r in requirements(spec))
    user = (
        f"{ROBOT}に、人が話しかける日本語の短い文を{n}個作ってください。\n\n"
        f"意味: {spec.meaning}\n\n"
        "条件:\n"
        f"- 文ごとに言い方を変える（例: {styles}）\n"
        f"- 1文は{60 if spec.id.startswith('focus.long_preface') else 40}文字以内\n"
        f"{extra}"
        "- 意味に含まれない動作や指示を足さない\n"
        "- 同じ言い回しを繰り返さない\n"
        '- 出力は {"sentences": [...]} の JSON だけ'
    )
    system = "あなたは、日本語の自然な話し言葉のデータを作る担当者です。"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def pair_schema(n: int) -> dict:
    item = {
        "type": "object",
        "properties": {
            "positive": {"type": "string", "minLength": 2, "maxLength": 60},
            "negative": {"type": "string", "minLength": 2, "maxLength": 60},
        },
        "required": ["positive", "negative"],
    }
    return {
        "type": "object",
        "properties": {"pairs": {"type": "array", "items": item, "minItems": n, "maxItems": n}},
        "required": ["pairs"],
    }


def pair_messages(spec: Spec, n: int) -> list[dict]:
    user = (
        f"{ROBOT}に話しかける日本語の文の組を{n}組作ってください。\n\n"
        f"positive: {spec.meaning}\n"
        "negative: positive とほぼ同じ言い方で、その動作を「しないで」と頼む文\n\n"
        "条件:\n"
        "- positive と negative の違いは、否定の部分だけにする\n"
        "- 組ごとに言い方を変える\n"
        "- 1文は40文字以内\n"
        '- 出力は {"pairs": [{"positive": "...", "negative": "..."}]} の JSON だけ'
    )
    return [{"role": "user", "content": user}]


def english_messages(spec: Spec, n: int) -> list[dict]:
    user = (
        f"Write {n} short, natural English sentences that a person might say to a small desktop "
        "robot that can turn its head left/right/up/down and show facial expressions on a "
        f"screen.\n\nMeaning (in Japanese): {spec.meaning}\n\n"
        "Vary the wording. Each sentence must be under 15 words. Do not add other actions.\n"
        "Write every sentence in English only (no Japanese characters).\n"
        'Output only JSON: {"sentences": [...]}'
    )
    return [{"role": "user", "content": user}]


VERIFY_SYSTEM = """あなたは、卓上ロボットへの日本語や英語の発話を、ロボットの動作の JSON に変換する担当者です。

使える動作は次の11個だけです。
- look: 正面を基準に首を向ける（絶対）。direction は left / right / up / down / up_left / up_right / down_left / down_right / center。amount（slight / normal / large）か degrees（1〜180 の整数）のどちらか一方
- turn: 今の向きから首を動かす（相対）。direction は center 以外。amount か degrees のどちらか一方
- nod: うなずく。count は 1〜5
- shake: 首を横に振る。count は 1〜5
- bow: お辞儀する。arguments は {}
- set_expression: 表情を変える。expression は happy / sad / surprised / neutral / angry / sleepy / doubt
- set_led: 台座のLEDライトの色。color は red / orange / yellow / green / light_blue / blue / purple / pink / white / off
- set_volume: スピーカーの音量。level は 0〜100
- adjust_volume: 音量を上げ下げする。direction は up / down、amount か by（1〜100）のどちらか一方
- set_brightness: 画面の明るさ。level は 0〜100
- adjust_brightness: 画面の明るさを上げ下げする。direction は up / down、amount か by のどちらか一方

規則:
- 発話が頼んでいる動作だけを、頼まれた順に、最大2個出力する。
- 否定された動作（〜しないで、〜ではなく）は出力しない。頼んでいる動作がなければ [] を出力する。
- 雑談、質問、あいさつ、気持ちの報告、ロボットにできない依頼、何をすべきか分からない依頼は [] を出力する。
- 部屋の照明・電気、エアコン、テレビなど、ロボット以外の機器の操作は [] を出力する。
- 「もう」「さらに」「もっと」「そこから」など、今の向きを基準にする言葉があれば turn、なければ look。
- 角度が数字で言われたら degrees（45、４５、四十五、45° はすべて 45）。数字がなければ amount。
- 「少し」「ちょっと」などは slight、「大きく」「思いっきり」などは large、それ以外は normal。
- 正面や真ん中を向くときは look の direction を center、amount を normal にする。
- 笑う・嬉しそう → happy、悲しそう・泣く → sad、驚く → surprised、真顔・普通の顔 → neutral、怒る → angry、眠そう → sleepy、不思議そう・困った顔 → doubt。
- うなずく回数、首を振る回数の指定がなければ count は 1。
- LED・ライトを消す → set_led の off。消音・ミュート → set_volume の 0。「半分」は 50、「最大」「いちばん大きく」は 100。100 を超える値は 100。
- 「音量を上げて」「明るくして」のように値がなければ adjust_volume / adjust_brightness（量の言葉がなければ amount は normal）。
- 「〜上げて」「〜下げて」「〜だけ」のように変える量なら adjust の by、「〜にして」のように値そのものなら set の level。
- 「最小」「いちばん小さく」は 0。
- 色の指定がなく LED・ライトを「つけて」なら set_led の white。
- JSON の配列だけを出力する。"""


def verify_messages(text: str) -> list[dict]:
    return [{"role": "system", "content": VERIFY_SYSTEM}, {"role": "user", "content": text}]


def action_response_format() -> dict:
    return {"type": "json_schema", "json_schema": {"name": "actions", "schema": load_schema()}}


def json_response_format(name: str, schema: dict) -> dict:
    return {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}


def dump_prompts() -> str:
    """Human-readable dump for the dataset card / manifest."""
    return json.dumps(
        {"version": PROMPT_VERSION, "verify_system": VERIFY_SYSTEM}, ensure_ascii=False, indent=2
    )
