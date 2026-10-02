# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Light sanity checks for generated sentences.

Deliberately NOT lexical label checks: requiring action keywords would keep only sentences that a
keyword rule can parse and would inflate the rule-based baseline. Labels are confirmed by the
cross-model verifier instead; these checks only remove malformed text and obvious negation mismatch.
The one exception is ``device_evidence``: it guards relabels of old (v0) [] rows, where the
verifier's answer is the only source of the new label (ruling R18), not the label-first new
sentences.
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


# Ruling R18: a v0 [] row may be relabeled only to device commands, and only when the prompt names
# the device of every call. Matched against normalize(text).lower() (NFKC folds full-width letters
# such as ＬＥＤ and half-width kana). Bare 音/声/光 or 明るく are not evidence: they also occur in
# narrative sentences and in requests the device commands cannot serve (音楽, 部屋を明るく).
DEVICE_EVIDENCE = {
    "led": r"led|ライト|ランプ",
    "volume": (
        r"音量|ボリューム|ミュート|消音|静かに|しずかに|うるさ"
        r"|音を(?:大きく|小さく|上げ|下げ)|声を(?:大きく|小さく)"
    ),
    "brightness": r"画面|明るさ",
}
_EVIDENCE_RE = {k: re.compile(v) for k, v in DEVICE_EVIDENCE.items()}
DEVICE_TOOLS = {
    "set_led": "led",
    "set_volume": "volume",
    "adjust_volume": "volume",
    "set_brightness": "brightness",
    "adjust_brightness": "brightness",
}


def device_evidence(text: str, calls: list[dict]) -> list[str]:
    """The device calls of ``calls`` whose device the prompt does not name ([] = accept).

    Calls to other tools are not checked: only device commands may relabel a [] row.
    """
    folded = normalize(text).lower()
    missing: list[str] = []
    for call in calls:
        key = DEVICE_TOOLS.get(call["name"])
        if key and not _EVIDENCE_RE[key].search(folded) and call["name"] not in missing:
            missing.append(call["name"])
    return missing
