# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Grammar-constrained decoding for Action schema v1.

Every target token is one fixed piece (``jtalm.model.format``), so the grammar is

    [] </s>
    [ CALL ] </s>
    [ CALL , CALL ] </s>        (the second call must differ from the first)

where CALL is any piece sequence of ``all_call_pieces()``: a call head, the first value, then for
look / turn / adjust_* a key and the second value, then a closer. Numbers are one token per digit
with no leading zero and stay inside the argument's range.

The calls form a trie that counts, for every prefix, how many complete calls lie below each next
piece. A piece is allowed when at least one of those calls differs from the first call, so the
grammar never reaches a dead end and never lets a duplicate through. Any output decoded under
this grammar parses, passes the schema, and has no duplicate call. The allowed ids are returned
in ascending order so that ties resolve like the C runtime (lowest id).
"""

from collections import defaultdict

from jtalm.model.data import Codec
from jtalm.model.format import all_call_pieces


class ActionGrammar:
    def __init__(self, codec: Codec) -> None:
        sp = codec.sp
        self.codec = codec
        self.eos = codec.eos

        def tid(piece: str) -> int:
            ids = sp.encode(piece)
            if len(ids) != 1:
                raise ValueError(f"{piece!r} is not a single token in {codec.path.name}")
            return ids[0]

        calls = all_call_pieces()
        pieces = {"[]", "[", "]", ","} | {p for c in calls for p in c}
        self.id = {p: tid(p) for p in sorted(pieces)}
        self.piece = {i: p for p, i in self.id.items()}
        self._complete = set(calls)
        self._below: dict[tuple[str, ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for c in calls:
            for k in range(len(c)):
                self._below[c[:k]][c[k]] += 1

    def _parse(self, generated: list[int]) -> tuple[str, list[tuple[str, ...]], tuple[str, ...]]:
        """Outer step, completed calls, and the pieces of the call being built."""
        step, calls, current = "start", [], ()
        for token in generated:
            piece = self.piece.get(token)
            if step == "start":
                step = "empty" if piece == "[]" else "call"
            elif step == "call":
                current = (*current, piece)
                if current in self._complete:
                    calls.append(current)
                    current = ()
                    step = "after_call"
            elif step == "after_call":
                step = "call" if piece == "," else "end"
            else:  # empty / end
                step = "done"
        return step, calls, current

    def allowed(self, generated: list[int]) -> list[int]:
        """Token ids allowed after ``generated`` (the target tokens produced so far), ascending."""
        step, calls, current = self._parse(generated)
        if step == "start":
            return sorted([self.id["[]"], self.id["["]])
        if step == "call":
            first = calls[0] if calls else None
            out = []
            for piece, n in self._below[current].items():
                if first is not None and first[: len(current) + 1] == (*current, piece):
                    n -= 1  # the first call itself is one of the calls below this piece
                if n > 0:
                    out.append(self.id[piece])
            return sorted(out)
        if step == "after_call":
            return sorted([self.id[","], self.id["]"]]) if len(calls) == 1 else [self.id["]"]]
        return [self.eos]  # "empty" / "end" / "done"
