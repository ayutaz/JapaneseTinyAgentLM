# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Sequence format shared by the tokenizer, training, and decoding.

One example is ``<s> <act> prompt <out> target </s>`` and the loss covers ``target </s>`` only.

The target is the compact JSON of the canonicalized calls with ``name`` first and the arguments in
schema order, e.g. ``[{"name":"look","arguments":{"direction":"right","amount":"normal"}}]``.
This differs from ``jtalm.action.schema.to_json`` (sorted keys, used for comparison) so that the
model decides the tool before its arguments. Both parse to the same calls.
"""

import json

from jtalm.action.schema import Call, canonicalize

ACT = "<act>"
OUT = "<out>"
ARG_ORDER = {
    "look": ("direction", "amount"),
    "set_expression": ("expression",),
    "nod": ("count",),
}

# Fixed JSON fragments of the target, each kept as one token (SentencePiece user-defined symbols).
# A single ``look`` call then takes 7 tokens: [ {..direction":" right ","amount":" normal "}} ].
JSON_PIECES = (
    "[]",
    "[",
    "]",
    ",",
    '{"name":"look","arguments":{"direction":"',
    '","amount":"',
    '{"name":"set_expression","arguments":{"expression":"',
    '{"name":"nod","arguments":{"count":',
    '"}}',
    "}}",
)
ENUM_VALUES = (
    "left", "right", "up", "down", "center",
    "slight", "normal", "large",
    "happy", "sad", "surprised", "neutral",
)  # fmt: skip


def target_json(calls: list[Call]) -> str:
    ordered = []
    for call in canonicalize(calls):
        args = call["arguments"]
        keys = ARG_ORDER.get(call["name"], ())
        arguments = {k: args[k] for k in keys if k in args}
        arguments.update({k: v for k, v in sorted(args.items()) if k not in arguments})
        ordered.append({"name": call["name"], "arguments": arguments})
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))
