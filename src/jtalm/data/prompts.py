"""Prompts for sentence generation and cross-model label verification (versioned)."""

import json

from jtalm.action.schema import load_schema
from jtalm.data.specs import Spec

PROMPT_VERSION = "action-v0.1"

ROBOT = "首を左右・上下に動かせて、画面に表情を出せる、小さな卓上ロボット"

STYLES_TRAIN = (
    "丁寧語、くだけた口語、短い命令、少し長めの依頼、子どもっぽい言い方、関西弁などの方言、"
    "句読点なし、ひらがな多め、文末に「〜ね」「〜よ」などを付ける"
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


def generation_messages(spec: Spec, n: int, split: str) -> list[dict]:
    styles = STYLES_TRAIN if split == "train" else STYLES_EVAL
    user = (
        f"{ROBOT}に、人が話しかける日本語の短い文を{n}個作ってください。\n\n"
        f"意味: {spec.meaning}\n\n"
        "条件:\n"
        f"- 文ごとに言い方を変える（例: {styles}）\n"
        "- 1文は40文字以内\n"
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
        'Output only JSON: {"sentences": [...]}'
    )
    return [{"role": "user", "content": user}]


VERIFY_SYSTEM = """あなたは、卓上ロボットへの日本語や英語の発話を、ロボットの動作の JSON に変換する担当者です。

使える動作は次の3つだけです。
- look: 首を向ける。direction は left / right / up / down / center、amount は slight / normal / large
- set_expression: 表情を変える。expression は happy / sad / surprised / neutral
- nod: うなずく。count は 1〜3

規則:
- 発話が頼んでいる動作だけを、頼まれた順に、最大2個出力する。
- 否定された動作（〜しないで、〜ではなく）は出力しない。頼んでいる動作がなければ [] を出力する。
- 雑談、質問、あいさつ、気持ちの報告、ロボットにできない依頼、何をすべきか分からない依頼は [] を出力する。
- 「少し」「ちょっと」などは slight、「大きく」「思いっきり」などは large、それ以外は normal。
- 正面や真ん中を向くときは direction を center、amount を normal にする。
- 笑う・嬉しそう → happy、悲しそう・泣く → sad、驚く → surprised、真顔・普通の顔 → neutral。
- うなずく回数の指定がなければ count は 1。
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
