"""Grammar-constrained decoding for Action schema v0 (M5).

Every target token is one of the fixed JSON pieces or enum values (``jtalm.model.format``), so the
schema is a small state machine over token ids:

    [] </s>
    [ CALL ] </s>
    [ CALL , CALL ] </s>        (the second call must differ from the first)

    CALL = LOOK direction ","amount":" amount "}}      (amount is normal when direction is center)
         | EXPRESSION expression "}}
         | NOD count }}                                  (count is 1..3)

Any output decoded under this grammar parses, passes the schema, and has no duplicate call.
"""

from dataclasses import dataclass, field

from jtalm.action.schema import AMOUNTS, DIRECTIONS, EXPRESSIONS
from jtalm.model.data import Codec

LOOK = '{"name":"look","arguments":{"direction":"'
AMOUNT_KEY = '","amount":"'
EXPR = '{"name":"set_expression","arguments":{"expression":"'
NOD = '{"name":"nod","arguments":{"count":'
COUNTS = ("1", "2", "3")


@dataclass
class _State:
    """Parser state after the tokens generated so far."""

    step: str = "start"
    calls: list[tuple] = field(default_factory=list)  # completed calls as (name, *values)
    current: list[str] = field(default_factory=list)  # name and values of the call being built


class ActionGrammar:
    def __init__(self, codec: Codec) -> None:
        sp = codec.sp
        self.eos = codec.eos

        def tid(piece: str) -> int:
            ids = sp.encode(piece)
            if len(ids) != 1:
                raise ValueError(f"{piece!r} is not a single token in {codec.path.name}")
            return ids[0]

        pieces = ("[]", "[", "]", ",", LOOK, AMOUNT_KEY, EXPR, NOD, '"}}', "}}")
        self.id = {p: tid(p) for p in pieces}
        self.values = {v: tid(v) for v in (*DIRECTIONS, *AMOUNTS, *EXPRESSIONS, *COUNTS)}
        self.piece = {i: p for p, i in {**self.id, **self.values}.items()}

    # -- state machine ---------------------------------------------------------------------------

    def _advance(self, state: _State, token: int) -> _State:
        piece = self.piece.get(token)
        s = state.step
        if s == "start":
            state.step = "empty" if piece == "[]" else "call"
        elif s == "call":
            name = {LOOK: "look", EXPR: "set_expression", NOD: "nod"}[piece]
            state.current = [name]
            state.step = {"look": "direction", "set_expression": "expression", "nod": "count"}[name]
        elif s == "direction":
            state.current.append(piece)
            state.step = "amount_key"
        elif s == "amount_key":
            state.step = "amount"
        elif s in ("amount", "expression", "count"):
            state.current.append(piece)
            state.step = "close"
        elif s == "close":
            state.calls.append(tuple(state.current))
            state.current = []
            state.step = "after_call"
        elif s == "after_call":
            state.step = "call" if piece == "," else "end"
        elif s in ("empty", "end"):
            state.step = "done"
        return state

    def state_of(self, generated: list[int]) -> _State:
        state = _State()
        for token in generated:
            state = self._advance(state, token)
        return state

    def allowed(self, generated: list[int]) -> list[int]:
        """Token ids allowed after ``generated`` (the target tokens produced so far)."""
        st = self.state_of(generated)
        first = st.calls[0] if st.calls else None
        s = st.step
        if s == "start":
            return [self.id["[]"], self.id["["]]
        if s == "call":
            return [self.id[LOOK], self.id[EXPR], self.id[NOD]]
        if s == "direction":
            dirs = list(DIRECTIONS)
            if first == ("look", "center", "normal"):
                dirs.remove("center")  # the only amount would duplicate the first call
            return [self.values[d] for d in dirs]
        if s == "amount_key":
            return [self.id[AMOUNT_KEY]]
        if s == "amount":
            direction = st.current[1]
            amounts = ["normal"] if direction == "center" else list(AMOUNTS)
            return self._not_duplicate(first, st.current, amounts)
        if s == "expression":
            return self._not_duplicate(first, st.current, list(EXPRESSIONS))
        if s == "count":
            return self._not_duplicate(first, st.current, list(COUNTS))
        if s == "close":
            return [self.id["}}"] if st.current[0] == "nod" else self.id['"}}']]
        if s == "after_call":
            return [self.id[","], self.id["]"]] if len(st.calls) == 1 else [self.id["]"]]
        return [self.eos]  # "empty" / "end" / "done"

    def _not_duplicate(
        self, first: tuple | None, current: list[str], options: list[str]
    ) -> list[int]:
        """Drop the last value that would make the call being built identical to the first."""
        if first is not None and first[:-1] == tuple(current):
            options = [o for o in options if o != first[-1]]
        return [self.values[o] for o in options]
