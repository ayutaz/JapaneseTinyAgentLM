"""Thin wrapper around the ``vastai`` CLI and SSH/SCP for running jobs on vast.ai.

Operating rules (docs/development.md section 4): never copy ``.env`` or other credentials to a
rented host, always destroy instances, and record cost for every run.
"""

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jtalm.infra.env import read_secret, redact

SSH_KEY = Path.home() / ".ssh" / "id_ed25519_vast"


class VastError(RuntimeError):
    pass


@dataclass(frozen=True)
class SshTarget:
    host: str
    port: int
    user: str = "root"


class VastClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or read_secret("VAST_API_KEY")
        exe = shutil.which("vastai")
        if exe is None:
            raise VastError("vastai CLI not found; run via `uv run`")
        self.exe = exe

    def _run(self, *args: str, timeout: int = 180) -> Any:
        # The key goes through the environment (not argv) so it never shows in process lists.
        proc = subprocess.run(
            [self.exe, *args, "--raw"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "VAST_API_KEY": self.api_key},
        )
        out = redact(proc.stdout + proc.stderr, self.api_key)
        if proc.returncode != 0:
            raise VastError(f"vastai {' '.join(args[:2])} failed: {out[:500]}")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise VastError(f"vastai {' '.join(args[:2])}: non-JSON output: {out[:300]}") from e

    def search_offers(self, query: str, order: str = "dph+") -> list[dict[str, Any]]:
        return self._run("search", "offers", query, "-o", order)

    def create_instance(self, offer_id: int, image: str, disk_gb: int, label: str) -> int:
        result = self._run(
            "create", "instance", str(offer_id),
            "--image", image,
            "--disk", str(disk_gb),
            "--label", label,
            "--ssh", "--direct", "--cancel-unavail",
        )  # fmt: skip
        instance_id = result.get("new_contract")
        if not result.get("success") or instance_id is None:
            raise VastError(f"create instance failed: {result}")
        return int(instance_id)

    def show_instance(self, instance_id: int) -> dict[str, Any]:
        return self._run("show", "instance", str(instance_id))

    def list_instance_ids(self) -> list[int]:
        return [int(i["id"]) for i in self._run("show", "instances")]

    def destroy_instance(self, instance_id: int) -> None:
        self._run("destroy", "instance", str(instance_id), "-y")

    def wait_running(self, instance_id: int, timeout_s: int = 1200) -> tuple[SshTarget, dict]:
        deadline = time.monotonic() + timeout_s
        info: dict[str, Any] = {}
        while time.monotonic() < deadline:
            info = self.show_instance(instance_id)
            if info.get("actual_status") == "running" and info.get("ssh_host"):
                return SshTarget(info["ssh_host"], int(info["ssh_port"])), info
            time.sleep(15)
        raise VastError(
            f"instance {instance_id} not running after {timeout_s}s: {info.get('status_msg')}"
        )


class Ssh:
    """SSH/SCP to a vast.ai instance with the project's dedicated key."""

    def __init__(self, target: SshTarget, known_hosts: Path, key: Path = SSH_KEY) -> None:
        self.target = target
        self.opts = [
            "-i", str(key),
            "-o", "StrictHostKeyChecking=no",
            "-o", f"UserKnownHostsFile={known_hosts.as_posix()}",
            "-o", "ServerAliveInterval=30",
            "-o", "ConnectTimeout=20",
        ]  # fmt: skip

    @property
    def dest(self) -> str:
        return f"{self.target.user}@{self.target.host}"

    def run(self, command: str, log: Path | None = None, timeout_s: int | None = None) -> int:
        """Run ``command`` with bash on the remote host, appending output to ``log``."""
        argv = [
            "ssh",
            *self.opts,
            "-p",
            str(self.target.port),
            self.dest,
            "bash",
            "-lc",
            _quote(command),
        ]
        with (log or Path(os.devnull)).open("a", encoding="utf-8") as f:
            f.write(f"\n$ {command}\n")
            f.flush()
            proc = subprocess.run(argv, stdout=f, stderr=subprocess.STDOUT, timeout=timeout_s)
        return proc.returncode

    def wait_ssh(self, attempts: int = 20) -> None:
        for _ in range(attempts):
            if self.run("echo ok", timeout_s=60) == 0:
                return
            time.sleep(15)
        raise VastError("ssh did not become available")

    def upload(self, local: Path, remote: str) -> None:
        self._scp([str(local), f"{self.dest}:{remote}"])

    def download(self, remote: str, local: Path) -> None:
        local.mkdir(parents=True, exist_ok=True)
        self._scp(["-r", f"{self.dest}:{remote}", str(local)])

    def _scp(self, args: list[str]) -> None:
        proc = subprocess.run(
            ["scp", *self.opts, "-P", str(self.target.port), *args],
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if proc.returncode != 0:
            raise VastError(f"scp failed: {proc.stderr[:300]}")


def _quote(command: str) -> str:
    return "'" + command.replace("'", "'\"'\"'") + "'"
