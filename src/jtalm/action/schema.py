# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Action schema v1: the tool table, parsing, validation, and canonicalization of model outputs.

An Action LM output is a JSON array of 0-2 calls such as
``[{"name": "look", "arguments": {"direction": "right", "degrees": 45}}]``.
``[]`` means no-action. ``TOOLS`` is the single source of truth: the JSON schema file, the
training target format, and the decoding grammar are all derived from it
(docs/superpowers/specs/2026-10-02-action-schema-v1-design.md).
"""

import json
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

Call = dict[str, Any]

DIRECTIONS = ("left", "right", "up", "down", "up_left", "up_right", "down_left", "down_right",
              "center")  # fmt: skip
TURN_DIRECTIONS = DIRECTIONS[:-1]
AMOUNTS = ("slight", "normal", "large")
EXPRESSIONS = ("happy", "sad", "surprised", "neutral", "angry", "sleepy", "doubt")
COLORS = ("red", "orange", "yellow", "green", "light_blue", "blue", "purple", "pink", "white",
          "off")  # fmt: skip
ADJUST_DIRECTIONS = ("up", "down")
DEGREES = (1, 180)
LEVEL = (0, 100)
BY = (1, 100)
COUNT = (1, 5)
MAX_CALLS = 2
SCHEMA_FILE = "action_schema_v1.json"


@dataclass(frozen=True)
class Arg:
    """One argument: an enum (``values``) or an inclusive integer ``range``."""

    name: str
    values: tuple[str, ...] = ()
    range: tuple[int, int] | None = None


@dataclass(frozen=True)
class Tool:
    """``first`` is the first argument (None: no arguments); exactly one of ``second`` follows."""

    first: Arg | None = None
    second: tuple[Arg, ...] = ()


_MAGNITUDE = (Arg("amount", AMOUNTS), Arg("degrees", range=DEGREES))
_ADJUST = (Arg("amount", AMOUNTS), Arg("by", range=BY))
TOOLS: dict[str, Tool] = {
    "look": Tool(Arg("direction", DIRECTIONS), _MAGNITUDE),
    "turn": Tool(Arg("direction", TURN_DIRECTIONS), _MAGNITUDE),
    "nod": Tool(Arg("count", range=COUNT)),
    "shake": Tool(Arg("count", range=COUNT)),
    "bow": Tool(),
    "set_expression": Tool(Arg("expression", EXPRESSIONS)),
    "set_led": Tool(Arg("color", COLORS)),
    "set_volume": Tool(Arg("level", range=LEVEL)),
    "adjust_volume": Tool(Arg("direction", ADJUST_DIRECTIONS), _ADJUST),
    "set_brightness": Tool(Arg("level", range=LEVEL)),
    "adjust_brightness": Tool(Arg("direction", ADJUST_DIRECTIONS), _ADJUST),
}
TOOL_NAMES = tuple(TOOLS)

# The v0 subset, for telling v0 labels from labels that need schema v1 (jtalm.data.build_v1).
_V0_DIRECTIONS = ("left", "right", "up", "down", "center")
_V0_EXPRESSIONS = ("happy", "sad", "surprised", "neutral")


def _arg_schema(arg: Arg) -> dict[str, Any]:
    if arg.values:
        return {"enum": list(arg.values)}
    assert arg.range is not None
    return {"type": "integer", "minimum": arg.range[0], "maximum": arg.range[1]}


def _call_schema(name: str, props: dict[str, Any]) -> dict[str, Any]:
    arguments = {"type": "object", "additionalProperties": False, "required": list(props),
                 "properties": props}  # fmt: skip
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "arguments"],
        "properties": {"name": {"const": name}, "arguments": arguments},
    }


def build_schema() -> dict[str, Any]:
    """The JSON schema of ``TOOLS`` (one ``oneOf`` item per tool and second-argument choice)."""
    items = []
    for name, tool in TOOLS.items():
        if tool.first is None:
            items.append(_call_schema(name, {}))
            continue
        first = {tool.first.name: _arg_schema(tool.first)}
        if not tool.second:
            items.append(_call_schema(name, first))
        for second in tool.second:
            items.append(_call_schema(name, {**first, second.name: _arg_schema(second)}))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://github.com/ayutaz/JapaneseTinyAgentLM/{SCHEMA_FILE}",
        "title": "JapaneseTinyAgentLM Action schema v1",
        "type": "array",
        "maxItems": MAX_CALLS,
        "items": {"oneOf": items},
    }


@cache
def load_schema() -> dict[str, Any]:
    text = resources.files("jtalm.action").joinpath(SCHEMA_FILE).read_text("utf-8")
    return json.loads(text)


@cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema())


@dataclass(frozen=True)
class ParsedOutput:
    """Result of parsing raw model text. ``calls`` is None when the text is not a JSON array."""

    raw: str
    calls: list[Call] | None
    errors: tuple[str, ...] = field(default=())

    @property
    def json_valid(self) -> bool:
        return self.calls is not None

    @property
    def schema_valid(self) -> bool:
        return self.calls is not None and not self.errors


def validate(calls: Any) -> list[str]:
    """Return schema violations plus project rules. Empty means valid.

    Project rules: no duplicate calls, and ``look`` toward center takes ``amount`` only.
    """
    errors = [e.message for e in _validator().iter_errors(calls)]
    if isinstance(calls, list):
        seen: set[str] = set()
        for call in calls:
            key = json.dumps(call, sort_keys=True, ensure_ascii=False)
            if key in seen:
                errors.append(f"duplicate call: {key}")
            seen.add(key)
            if (
                isinstance(call, dict)
                and call.get("name") == "look"
                and isinstance(call.get("arguments"), dict)
                and call["arguments"].get("direction") == "center"
                and "degrees" in call["arguments"]
            ):
                errors.append("look toward center takes no degrees")
    return errors


def parse_output(raw: str) -> ParsedOutput:
    """Parse raw model text into calls and validate them."""
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ParsedOutput(raw=raw, calls=None, errors=("not valid JSON",))
    if not isinstance(value, list):
        return ParsedOutput(raw=raw, calls=None, errors=("top level is not a JSON array",))
    return ParsedOutput(raw=raw, calls=value, errors=tuple(validate(value)))


def canonicalize(calls: list[Call]) -> list[Call]:
    """Normalize calls for comparison. Order is kept because it is part of the meaning.

    ``look`` with ``direction == "center"`` ignores ``amount``, so it is normalized to ``normal``.
    """
    canonical: list[Call] = []
    for call in calls:
        args = dict(call.get("arguments", {}))
        if call.get("name") == "look" and args.get("direction") == "center" and "amount" in args:
            args["amount"] = "normal"
        canonical.append({"name": call.get("name"), "arguments": args})
    return canonical


def to_json(calls: list[Call]) -> str:
    """Serialize calls in the compact canonical form (sorted keys) used for comparison and records.

    Training targets use ``jtalm.model.format.target_json`` (name first), which parses the same.
    """
    return json.dumps(
        canonicalize(calls), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def uses_v1_only(calls: list[Call]) -> bool:
    """True when some call cannot be written in schema v0 (a new tool, value, or argument)."""
    for call in calls:
        name, args = call["name"], call["arguments"]
        if name not in ("look", "set_expression", "nod"):
            return True
        if name == "look" and ("degrees" in args or args["direction"] not in _V0_DIRECTIONS):
            return True
        if name == "set_expression" and args["expression"] not in _V0_EXPRESSIONS:
            return True
        if name == "nod" and int(args["count"]) > 3:
            return True
    return False


def main() -> None:
    """Write the JSON schema file from ``TOOLS`` (run after changing the table)."""
    path = Path(__file__).with_name(SCHEMA_FILE)
    path.write_text(json.dumps(build_schema(), indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
