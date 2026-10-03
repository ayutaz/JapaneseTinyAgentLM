# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Sequence format shared by the tokenizer, training, and decoding.

One example is ``<s> <act> prompt <out> target </s>`` and the loss covers ``target </s>`` only.

The target is the compact JSON of the canonicalized calls with ``name`` first and the arguments in
schema order, e.g. ``[{"name":"look","arguments":{"direction":"right","degrees":45}}]``.
This differs from ``jtalm.action.schema.to_json`` (sorted keys, used for comparison) so that the
model decides the tool before its arguments. Both parse to the same calls.

Every target is a sequence of fixed pieces, each one SentencePiece token (user-defined symbols):
the head of a call (its name and first key), a key between two arguments, a closer, an enum
value, or one digit of a number. A ``look`` call with 45 degrees is
``{"name":"look","arguments":{"direction":"`` ``right`` ``","degrees":`` ``4`` ``5`` ``}}``.
"""

import json

from jtalm.action.schema import TOOLS, Arg, Call, canonicalize

ACT = "<act>"
OUT = "<out>"
DIGITS = tuple("0123456789")
ARG_ORDER = {
    name: tuple(a.name for a in (tool.first, *tool.second) if a is not None)
    for name, tool in TOOLS.items()
}


def _quote(arg: Arg) -> str:
    return '"' if arg.values else ""


def head_piece(name: str) -> str:
    """The call up to its first value: ``{"name":"nod","arguments":{"count":``."""
    first = TOOLS[name].first
    if first is None:
        return f'{{"name":"{name}","arguments":{{}}}}'  # a whole call (bow)
    return f'{{"name":"{name}","arguments":{{"{first.name}":{_quote(first)}'


def key_piece(arg: Arg) -> str:
    """Between the (string) first value and ``arg``: ``","degrees":``."""
    return f'","{arg.name}":{_quote(arg)}'


def close_piece(arg: Arg) -> str:
    return '"}}' if arg.values else "}}"


def _options(arg: Arg) -> list[tuple[str, ...]]:
    if arg.values:
        return [(v,) for v in arg.values]
    assert arg.range is not None
    return [tuple(str(n)) for n in range(arg.range[0], arg.range[1] + 1)]


def all_call_pieces() -> list[tuple[str, ...]]:
    """Every valid call as its piece sequence (``look`` center takes only amount normal)."""
    calls: list[tuple[str, ...]] = []
    for name, tool in TOOLS.items():
        head = head_piece(name)
        if tool.first is None:
            calls.append((head,))
            continue
        for value in _options(tool.first):
            if not tool.second:
                calls.append((head, *value, close_piece(tool.first)))
                continue
            assert tool.first.values, "a second argument follows a string value"
            for second in tool.second:
                options = _options(second)
                if name == "look" and value == ("center",):
                    if second.name != "amount":
                        continue
                    options = [("normal",)]
                for w in options:
                    calls.append((head, *value, key_piece(second), *w, close_piece(second)))
    return calls


def _unique(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


JSON_PIECES = _unique(
    ["[]", "[", "]", ","]
    + [head_piece(n) for n in TOOLS]
    + [key_piece(a) for t in TOOLS.values() for a in t.second]
    + ['"}}', "}}"]
)
ENUM_VALUES = _unique(
    [v for t in TOOLS.values() for a in (t.first, *t.second) if a is not None for v in a.values]
    + list(DIGITS)
)


def target_json(calls: list[Call]) -> str:
    ordered = []
    for call in canonicalize(calls):
        args = call["arguments"]
        keys = ARG_ORDER.get(call["name"], ())
        arguments = {k: args[k] for k in keys if k in args}
        arguments.update({k: v for k, v in sorted(args.items()) if k not in arguments})
        ordered.append({"name": call["name"], "arguments": arguments})
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))
