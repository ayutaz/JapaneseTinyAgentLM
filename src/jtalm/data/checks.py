"""Light sanity checks for generated sentences.

Deliberately NOT lexical label checks: requiring action keywords would keep only sentences that a
keyword rule can parse and would inflate the rule-based baseline. Labels are confirmed by the
cross-model verifier instead; these checks only remove malformed text and obvious negation mismatch.
"""

import re
import unicodedata

JA_CHARS = re.compile(r"[぀-ヿ一-鿿]")
NEGATION_JA = re.compile(
    r"(ないで|なくていい|なくて(?:も)?いい|しなくて|やめて|だめ|ダメ|禁止|するな|な(?:い)?でね|な$)"
)
CONTRAST_JA = re.compile(
    r"(ではなく|じゃなくて|じゃなく|でなく|ないで|なくて|やめて|違う|ちがう|より)"
)
NEGATION_EN = re.compile(r"\b(don't|do not|dont|never|stop|no need)\b", re.IGNORECASE)
PUNCT_OR_SPACE = re.compile(r"[\s　、。，．,.!！?？・「」『』（）()\"'〜~ー…]+")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


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
        return CONTRAST_JA.search(normalize(text)) is not None
    return True
