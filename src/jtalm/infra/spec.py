# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Job specification for vast.ai runs."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class JobSpec:
    name: str
    description: str
    query: str  # vastai search offers query
    image: str
    disk_gb: int
    max_hours: float
    steps: list[str]  # bash commands run in the remote work directory, in order
    fetch: list[str] = field(default_factory=lambda: ["artifacts"])
    # Local files (paths relative to the project root) copied to the same relative path in the
    # remote work directory, e.g. gitignored datasets that ``git archive`` does not include.
    # Their sha256 is recorded in run.json and checked on the instance before the steps run.
    uploads: list[str] = field(default_factory=list)
