# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Keyword rule baseline for the Action LM (the "simple method" the model must beat).

Clauses are split on Japanese punctuation and connectives; negated clauses are dropped; the text
after 「ではなく」 replaces what came before it; action cues are ordered by their position.
"""

import json
import re

from jtalm.action.schema import Call, to_json

LOOK_DIR = [
    ("right", r"右|みぎ|ミギ|\bright\b"),
    ("left", r"左|ひだり|ヒダリ|\bleft\b"),
    ("up", r"上を|上に|うえ|見上げ|\bup\b"),
    ("down", r"下を|下に|した[をに]|うつむ|見下ろ|\bdown\b"),
    ("center", r"正面|まっすぐ|真っ直ぐ|真ん中|前を向|\bforward\b|\bcenter\b|\bstraight\b"),
]
LOOK_VERB = r"向|見|顔|首|turn|look|face"
AMOUNT = [
    ("slight", r"少し|すこし|ちょっと|ちょこっと|軽く|わずか|やや|slightly|a (?:little|bit)"),
    (
        "large",
        r"大きく|思いっきり|思い切り|おもいっきり|ぐっと|しっかり|めいっぱい|all the way|far",
    ),
]
EXPRESSION = [
    ("happy", r"笑|嬉|うれし|喜|にこ|ニコ|楽しそう|smile|happy"),
    ("sad", r"悲し|かなし|泣|しょんぼり|寂し|さみし|\bsad\b"),
    ("surprised", r"驚|おどろ|びっくり|ビックリ|surprise"),
    ("neutral", r"真顔|普通の顔|無表情|いつもの顔|neutral"),
]
NOD = r"うなず|頷|首を縦|\bnod"
COUNT = [(3, r"3|三|３|three"), (2, r"2|二|２|twice|two"), (1, r"1|一|１|once")]
NEGATION = r"ないで|なくていい|しなくて|やめて|だめ|ダメ|するな|don't|do not|never"
CORRECTION = r"ではなく|じゃなくて|じゃなく|でなく|instead of"
CLAUSE_SPLIT = r"[、。,.!?！？]|てから|たら|そのあと|それから|and then|then|, and"


def _find(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.start() if m else None


def _clause_calls(clause: str) -> list[tuple[int, Call]]:
    found: list[tuple[int, Call]] = []
    if _find(LOOK_VERB, clause) is not None:
        for direction, pat in LOOK_DIR:
            pos = _find(pat, clause)
            if pos is not None:
                amount = next((a for a, p in AMOUNT if _find(p, clause) is not None), "normal")
                if direction == "center":
                    amount = "normal"
                args = {"direction": direction, "amount": amount}
                found.append((pos, {"name": "look", "arguments": args}))
                break
    for value, pat in EXPRESSION:
        pos = _find(pat, clause)
        if pos is not None:
            found.append((pos, {"name": "set_expression", "arguments": {"expression": value}}))
            break
    pos = _find(NOD, clause)
    if pos is not None:
        count = next((c for c, p in COUNT if _find(p, clause) is not None), 1)
        found.append((pos, {"name": "nod", "arguments": {"count": count}}))
    return found


def predict(text: str) -> list[Call]:
    if (pos := _find(CORRECTION, text)) is not None:
        text = text[pos:]
        text = re.sub(CORRECTION, "", text, count=1, flags=re.IGNORECASE)
    calls: list[tuple[int, Call]] = []
    offset = 0
    for clause in re.split(CLAUSE_SPLIT, text, flags=re.IGNORECASE):
        if clause and _find(NEGATION, clause) is None:
            calls.extend((offset + p, c) for p, c in _clause_calls(clause))
        offset += len(clause) + 1
    ordered: list[Call] = []
    for _, call in sorted(calls, key=lambda pc: pc[0]):
        if call not in ordered:
            ordered.append(call)
    return ordered[:2]


def predict_json(text: str) -> str:
    return to_json(predict(text)) if predict(text) else json.dumps([])
