"""Light sanity checks for generated sentences.

Deliberately NOT lexical label checks: requiring action keywords would keep only sentences that a
keyword rule can parse and would inflate the rule-based baseline. Labels are confirmed by the
cross-model verifier instead; these checks only remove malformed text and obvious negation mismatch.
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
