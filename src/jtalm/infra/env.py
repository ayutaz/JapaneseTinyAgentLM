# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Read secrets from the project's ``.env`` without ever printing them."""

import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def read_secret(name: str, env_file: Path | None = None) -> str:
    """Return ``name`` from the environment or from ``.env`` (UTF-8, BOM tolerated)."""
    if value := os.environ.get(name):
        return value
    path = env_file or PROJECT_ROOT / ".env"
    if path.exists():
        pattern = re.compile(rf"\s*(?:export\s+)?{re.escape(name)}\s*=\s*['\"]?([^'\"\s#]+)")
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if m := pattern.match(line):
                return m.group(1)
    raise KeyError(f"{name} is not set in the environment or {path}")


def redact(text: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text
