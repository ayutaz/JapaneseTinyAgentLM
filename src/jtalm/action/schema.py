# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Action schema v0: parsing, validation, and canonicalization of model outputs.

An Action LM output is a JSON array of 0-2 calls such as
``[{"name": "look", "arguments": {"direction": "right", "amount": "normal"}}]``.
``[]`` means no-action. See docs/architecture.md section 7.
"""

import json
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

Call = dict[str, Any]

TOOL_NAMES = ("look", "set_expression", "nod")
DIRECTIONS = ("left", "right", "up", "down", "center")
AMOUNTS = ("slight", "normal", "large")
EXPRESSIONS = ("happy", "sad", "surprised", "neutral")
MAX_CALLS = 2


@cache
def load_schema() -> dict[str, Any]:
    text = resources.files("jtalm.action").joinpath("action_schema_v0.json").read_text("utf-8")
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
    """Return schema violations plus project rules (no duplicate calls). Empty means valid."""
    errors = [e.message for e in _validator().iter_errors(calls)]
    if isinstance(calls, list):
        seen: set[str] = set()
        for call in calls:
            key = json.dumps(call, sort_keys=True, ensure_ascii=False)
            if key in seen:
                errors.append(f"duplicate call: {key}")
            seen.add(key)
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
        if call.get("name") == "look" and args.get("direction") == "center":
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
