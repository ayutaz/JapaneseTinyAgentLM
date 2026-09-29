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
