# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Light sanity checks for generated sentences.

Deliberately NOT lexical label checks: requiring action keywords would keep only sentences that a
keyword rule can parse and would inflate the rule-based baseline. Labels are confirmed by the
cross-model verifier instead; these checks only remove malformed text and obvious negation mismatch.
The one exception is ``v1_evidence``: it guards relabels of old (v0) rows, where the verifier's
answer is the only source of the new label (ruling R15), not the label-first new sentences.
"""

import re
import unicodedata

JA_CHARS = re.compile(r"[぀-ヿ一-鿿]")
NEGATION_JA = re.compile(
    r"(ないで|ないように|なくて|なくても|ずに|(?<![まえ])ず[、,。]|んといて|へんといて|ひんといて|んで(?:ね|よ)|"
    r"[^ら]んな[!！。よ]?$|[くぐすつぬぶむるう]な(?:よ|[!！。、\s]|$)|ませんように|んじゃね|やめ|だめ|ダメ|禁止|いらない|いらん|不要|結構|控え|しなくて)"
)
CONTRAST_JA = re.compile(
    r"(ではなく|じゃなくて|じゃなく|でなく|やなくて|ちゃう|やっぱり|やっぱ|って言ったけど|と言ったけど|"
    r"代わりに|かわりに|取り消|違う|ちがう|変えて|より)"
)
NEGATION_EN = re.compile(r"\b(don't|do not|dont|never|stop|no need|not)\b", re.IGNORECASE)
QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})
PUNCT_OR_SPACE = re.compile(r"[\s　、。，．,.!！?？・「」『』（）()\"'〜~ー…]+")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(QUOTES).strip()


def dedup_key(text: str) -> str:
    return PUNCT_OR_SPACE.sub("", normalize(text).lower())


def well_formed(text: str, language: str) -> bool:
    text = normalize(text)
    if not 2 <= len(text) <= 60 or "\n" in text or any(c in text for c in "{}[]<>"):
        return False
    return bool(JA_CHARS.search(text)) if language == "ja" else text.isascii()


def negation_consistent(text: str, category: str, language: str) -> bool:
    """Reject positive commands that contain a negation and negations that contain none."""
    neg = (NEGATION_JA if language == "ja" else NEGATION_EN).search(normalize(text))
    if category in ("single", "multi_action"):
        return neg is None
    if category == "negation":
        return neg is not None
    if category == "correction" and language == "ja":
        text = normalize(text)
        return CONTRAST_JA.search(text) is not None or NEGATION_JA.search(text) is not None
    return True


# Ruling R15: a relabel of a v0 row into schema v1 is accepted only when every v1-only element of
# the new label has a word for it in the prompt. Matched against normalize(text).lower() (NFKC
# folds full-width digits/letters and half-width kana). v0 elements need no evidence.
_KANJI_DIGITS = "一二三四五六七八九十百"
V1_EVIDENCE = {
    "turn": (
        r"もう|さらに|もっと|そこから|今の向きから|今の位置から|あと(?:少し|ちょっと)|追加で|続けて"
    ),
    "degrees": rf"[0-9{_KANJI_DIGITS}][^0-9{_KANJI_DIGITS}]{{0,3}}?(?:度|°)",
    "diagonal": r"右上|左上|右下|左下|斜め|ななめ",
    "set_led": r"led|ライト|光|ひかり|点灯|消灯|ランプ",
    "volume": r"音量|ボリューム|音|声|静か|しずか|うるさ|ミュート|消音",
    "brightness": r"明るさ|明るく|暗く|画面|まぶし|眩し",
    "shake": r"首を(?:横に)?振|首振|横に振|いやいや|イヤイヤ|ぶんぶん|ふるふる|かぶりを",
    "bow": r"お辞儀|おじぎ|オジギ|礼|一礼|頭を下げ",
    "set_expression:angry": r"怒|おこ|ぷんぷん|むっ|ムッ",
    "set_expression:sleepy": r"眠|ねむ|あくび|うとうと",
    "set_expression:doubt": (
        r"不思議|ふしぎ|困|はてな|ハテナ|首をかしげ|首を傾げ|きょとん|[?？]顔|疑問"
    ),
    "nod:count=4": r"4|四",
    "nod:count=5": r"5|五",
}
_EVIDENCE_RE = {k: re.compile(v) for k, v in V1_EVIDENCE.items()}
_DIAGONALS = ("up_left", "up_right", "down_left", "down_right")


def _v1_elements(call: dict) -> list[tuple[str, str]]:
    """(element reported when missing, V1_EVIDENCE key) for each v1-only element of one call."""
    name, args = call["name"], call.get("arguments") or {}
    out: list[tuple[str, str]] = []
    if name == "turn":
        out.append(("turn", "turn"))
    if name in ("look", "turn"):
        if "degrees" in args:
            out.append(("degrees", "degrees"))
        if args.get("direction") in _DIAGONALS:
            out.append(("diagonal", "diagonal"))
    elif name in ("set_led", "shake", "bow"):
        out.append((name, name))
    elif name in ("set_volume", "adjust_volume"):
        out.append((name, "volume"))
    elif name in ("set_brightness", "adjust_brightness"):
        out.append((name, "brightness"))
    elif name == "set_expression" and args.get("expression") in ("angry", "sleepy", "doubt"):
        key = f"set_expression:{args['expression']}"
        out.append((key, key))
    elif name == "nod" and str(args.get("count")) in ("4", "5"):
        out.append(("nod:count", f"nod:count={args['count']}"))
    return out


def v1_evidence(text: str, calls: list[dict]) -> list[str]:
    """The v1-only elements of ``calls`` that have no lexical evidence in ``text`` ([] = accept)."""
    folded = normalize(text).lower()
    missing: list[str] = []
    for call in calls:
        for element, key in _v1_elements(call):
            if not _EVIDENCE_RE[key].search(folded) and element not in missing:
                missing.append(element)
    return missing
