"""Focused specs: one "slice" per phrasing pattern (evaluation set v2 and training data v0.5).

The same label-first specs serve two purposes, always with different writers:
- evaluation set v2: llm-jp-3.1 writes the sentences (eval-only writer), Qwen3 verifies;
- training data v0.5: the seven training writers write, Qwen3 verifies.
The slices come from the weaknesses found on the human-written set (docs/roadmap.md section 12)
and from the phrasing patterns we want to track. Spec ids are ``focus.<slice>.<detail>``.
"""

import random

from jtalm.data.specs import (
    Spec,
    correction_specs,
    describe,
    expression,
    look,
    multi_specs,
    negation_specs,
    nod,
    single_specs,
)

SLICES = (
    "center_phrasing",
    "amount_words",
    "numbers",
    "negation_forms",
    "correction",
    "order_words",
    "fragments",
    "unexecutable",
    "orthography",
    "question_forms",
    "long_preface",
    "english",
    "imperative_forms",
    "kanji_kudasai",
)


def _spec(slice_: str, detail: str, category: str, label: tuple, meaning: str, hint: str,
          hint_only: bool = False) -> Spec:  # fmt: skip
    return Spec(f"focus.{slice_}.{detail}", category, label, meaning, hint, hint_only)


def slice_of(spec_id: str) -> str | None:
    parts = spec_id.split(".")
    return parts[1] if len(parts) > 2 and parts[0] == "focus" else None


def center_phrasing() -> list[Spec]:
    return [
        _spec("center_phrasing", "center", "single", (look("center"),),
              "ロボットに、話し手の方（正面）を向くように頼む",
              "「こっち」「こちら」「私の方」「僕の方」「前」のどれかを使って、話し手の方や正面を"
              "向く（見る）ように頼む。「向いて」だけでなく「見て」も使う", hint_only=True),
        _spec("center_phrasing", "face_up", "single", (look("up"),),
              "ロボットに、顔を上げるように頼む",
              "「顔を上げて」「顔を上に向けて」「上を見上げて」のように、顔を上げる言い方で頼む",
              hint_only=True),
    ]  # fmt: skip


AMOUNT_HINT = {
    "slight": "動きが小さいことを「ちょっとだけ」「ほんの少し」「軽く」「ちょこっと」「わずかに」"
    "などで表す（「少し」ばかりにしない）",
    "large": "動きが大きいことを「めいっぱい」「思い切り」「ぐいっと」「うんと」「大きく」など"
    "で表す（「大きく」ばかりにしない）",
}


def amount_words() -> list[Spec]:
    return [
        _spec("amount_words", f"{d}.{a}", "single", (look(d, a),),
              f"ロボットに「{describe(look(d, a))}」ように頼む", AMOUNT_HINT[a], hint_only=True)
        for d in ("left", "right", "up", "down") for a in ("slight", "large")
    ]  # fmt: skip


def numbers() -> list[Spec]:
    specs = [
        _spec("numbers", f"nod{c}", "single", (nod(c),), f"ロボットに{c}回うなずくように頼む",
              f"回数を「{c}回」「{'二' if c == 2 else '三'}回」のように数字で入れる",
              hint_only=True)
        for c in (2, 3)
    ]  # fmt: skip
    specs.append(
        _spec("numbers", "no_action", "no_action", (),
              "ロボットに話しかける、数字を含む雑談や質問",
              "時刻、日付、数量、回数、順番（2回目、3時、5分後、1位 など）の数字を含むが、"
              "ロボットの動作は頼まない文にする", hint_only=True)
    )  # fmt: skip
    return specs


def negation_forms() -> list[Spec]:
    hint = (
        "否定の形は「〜しないで」以外にする（「〜しなくていい」「〜はダメ」「〜するな」"
        "「〜しちゃだめ」「〜はやめておいて」「〜はいらない」など）"
    )
    return [
        _spec("negation_forms", s.id.removeprefix("negation."), "negation", s.label, s.meaning,
              hint, hint_only=True)
        for s in negation_specs()
    ]  # fmt: skip


def correction() -> list[Spec]:
    return [_spec("correction", s.id.removeprefix("correction."), "correction", s.label,
                  s.meaning, "") for s in correction_specs()]  # fmt: skip


def order_words() -> list[Spec]:
    hint = (
        "2つの動作の順序を「〜してから」「〜したあとで」「まず〜、それから〜」「〜の次に」"
        "「〜し終わったら」などの言葉で表す"
    )
    return [_spec("order_words", s.id.removeprefix("multi_action."), "multi_action", s.label,
                  s.meaning, hint) for s in multi_specs()]  # fmt: skip


def fragments() -> list[Spec]:
    return [
        _spec("fragments", "fragment", "no_action", (),
              "ロボットに話しかけた、短い断片や名詞だけの発話",
              "人名、作品名、番組名、商品名、地名、店名、単語だけ、数字を含む名詞など、1〜10文字"
              "くらいの短い断片にする（依頼の形にしない）", hint_only=True),
    ]  # fmt: skip


def unexecutable() -> list[Spec]:
    return [
        _spec("unexecutable", "household", "no_action", (),
              "ロボットにはできない家事や物の操作の依頼",
              "「右」「左」「上」「下」「奥」「手前」「二段目」「上の棚」などの位置の言葉を含むが、"
              "物を取る・置く・運ぶ・片付ける・開ける依頼にする（首や顔の向きの依頼にはしない）",
              hint_only=True),
        _spec("unexecutable", "directions", "no_action", (),
              "道順や場所の説明",
              "「右に曲がって」「左側にある」「上の階」など方向の言葉を含む、道順や物の場所の"
              "説明や質問にする（ロボットに首を向けさせる依頼にはしない）", hint_only=True),
    ]  # fmt: skip


ORTHOGRAPHY = {
    "hiragana": "漢字を使わず、ひらがなだけで書く",
    "katakana": "カタカナの言葉を多めに混ぜる（ミギ、ニッコリ、ストップ など）",
    "typo": "打ち間違いや変換ミスを1か所だけ入れる（意味は分かるようにする）",
    "dialect": "関西弁、博多弁、東北弁などの方言で書く",
}


def orthography() -> list[Spec]:
    bases = [
        *(s for s in single_specs() if s.label[0]["name"] != "look" or
          s.label[0]["arguments"]["amount"] == "normal"),
    ]  # fmt: skip
    specs = []
    for key, hint in ORTHOGRAPHY.items():
        specs += [_spec("orthography", f"{key}.{s.id.removeprefix('single.')}", "single",
                        s.label, s.meaning, hint) for s in bases]  # fmt: skip
        specs.append(_spec("orthography", f"{key}.no_action", "no_action", (),
                           "ロボットへの雑談やあいさつ", hint, hint_only=True))  # fmt: skip
    return specs


def question_forms() -> list[Spec]:
    hint = (
        "「〜してくれる？」「〜できる？」「〜してもらえる？」「〜してくれない？」など疑問形で頼む"
    )
    return [_spec("question_forms", s.id.removeprefix("single."), "single", s.label, s.meaning,
                  hint) for s in single_specs()]  # fmt: skip


def long_preface() -> list[Spec]:
    hint = (
        "頼む前に、自分の状況や気持ち、理由を一言そえる（全体で25〜55文字）。"
        "前置きの中では別の動作を頼まない"
    )
    pool = [s for s in single_specs()] + [s for s in multi_specs()][:40]
    return [_spec("long_preface", s.id, s.category, s.label, s.meaning, hint) for s in pool]


def imperative_forms() -> list[Spec]:
    """Plain / rough imperatives (見ろ, 向け, 笑え, うなずけ); v0.5 gated these (low confidence)."""
    hint = (
        "ぶっきらぼうな命令形で頼む（「見ろ」「向け」「向きなさい」「笑え」「うなずけ」「〜しろ」"
        "「〜してくれ」など）。「ください」「てね」のような丁寧な言い方は使わない"
    )
    return [_spec("imperative_forms", s.id.removeprefix("single."), "single", s.label, s.meaning,
                  hint) for s in single_specs()]  # fmt: skip


def kanji_kudasai() -> list[Spec]:
    """Requests ending in 下さい (kanji): v0.5 read the 下 of 下さい as the direction 'down'."""
    hint = "文末を漢字の「下さい」にする（例: 「〜して下さい」「〜を見て下さい」）"
    return [_spec("kanji_kudasai", s.id.removeprefix("single."), "single", s.label, s.meaning,
                  hint) for s in single_specs()]  # fmt: skip


def focus_specs() -> list[Spec]:
    """All focused specs except English (English uses the existing English prompt)."""
    return (
        center_phrasing() + amount_words() + numbers() + negation_forms() + correction()
        + order_words() + fragments() + unexecutable() + orthography() + question_forms()
        + long_preface()
        + imperative_forms()
        + kanji_kudasai()
    )  # fmt: skip


def sample_by_slice(
    specs: list[Spec], quota: dict[str, int], per_request: int, rng: random.Random
) -> list[Spec]:
    """Spread a per-slice sentence quota evenly over the specs of each slice."""
    requests: list[Spec] = []
    for slice_, target in quota.items():
        pool = [s for s in specs if slice_of(s.id) == slice_]
        if not pool:
            raise ValueError(f"no specs for slice {slice_}")
        n_requests = -(-target // per_request)
        cycle = [pool[i % len(pool)] for i in range(n_requests)]
        rng.shuffle(cycle)
        requests.extend(cycle)
    return requests


def english_pool() -> list[Spec]:
    """Specs for the English slice (written with prompts.english_messages)."""
    return [s for s in single_specs() + negation_specs()] + [
        Spec("focus.english.no_action", "no_action", (), "ロボットへの雑談や質問"),
        Spec("focus.english.expr", "single", (expression("happy"),), "ロボットに笑うように頼む"),
    ]
