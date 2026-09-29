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

# Some images (e.g. vllm/vllm-openai) ship a group/world-writable /root, so sshd's StrictModes
# refuses /root/.ssh/authorized_keys ("bad ownership or modes"). Fix the modes at container start.
ONSTART_FIX_SSH = (
    "chown root:root /root; chmod 755 /root; "
    "mkdir -p /root/.ssh; chown -R root:root /root/.ssh; chmod 700 /root/.ssh; "
    "chmod 600 /root/.ssh/authorized_keys 2>/dev/null; true"
)


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

    def _run(self, *args: str, timeout: int = 180, parse: bool = True) -> Any:
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
        if not parse:
            return out
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise VastError(f"vastai {' '.join(args[:2])}: non-JSON output: {out[:300]}") from e

    def search_offers(self, query: str, order: str = "dph+") -> list[dict[str, Any]]:
        return self._run("search", "offers", query, "-o", order)

    def create_instance(
        self, offer_id: int, image: str, disk_gb: int, label: str, onstart: str = ""
    ) -> int:
        result = self._run(
            "create", "instance", str(offer_id),
            "--image", image,
            "--disk", str(disk_gb),
            "--label", label,
            "--onstart-cmd", onstart or ONSTART_FIX_SSH,
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
        """Destroy an instance; an instance that is already gone counts as destroyed."""
        out = self._run("destroy", "instance", str(instance_id), "-y", parse=False)
        if '"error": true' in out and "not found" not in out.lower():
            raise VastError(f"destroy {instance_id} failed: {out[:300]}")

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

    def output(self, command: str, timeout_s: int = 60) -> tuple[int, str]:
        """Run a short command and return (exit code, stdout); 255 means SSH itself failed."""
        argv = ["ssh", *self.opts, "-p", str(self.target.port), self.dest, "bash", "-lc"]
        try:
            proc = subprocess.run(
                [*argv, _quote(command)], capture_output=True, text=True, timeout=timeout_s
            )
        except subprocess.TimeoutExpired:
            return 255, ""
        return proc.returncode, proc.stdout

    def run_detached(
        self, command: str, name: str, log: Path, timeout_s: int, poll_s: int = 20
    ) -> int:
        """Run ``command`` on the host independently of the SSH session and wait for it.

        The vast.ai SSH proxy sometimes closes long sessions, which used to kill the step with
        it (exit 255). Here the command runs under ``setsid nohup`` and writes its exit code to
        a file; short SSH calls poll for that file and are retried when the proxy drops them.
        Launching is idempotent (a marker file), so a dropped launch can simply be retried.
        """
        d = "/root/.jtalm_steps"
        script = f"{d}/{name}.sh"
        launch = (
            f"mkdir -p {d}; if [ ! -e {d}/{name}.started ]; then touch {d}/{name}.started; "
            f"cat > {script} <<'JTALM_STEP_EOF'\n{command}\nJTALM_STEP_EOF\n"
            f"setsid nohup bash -c 'bash -l {script} > {d}/{name}.log 2>&1; "
            f"echo $? > {d}/{name}.rc' > /dev/null 2>&1 < /dev/null & fi; echo launched"
        )
        with log.open("a", encoding="utf-8") as f:
            f.write(f"\n$ {command}\n")
        deadline = time.monotonic() + timeout_s
        failures = 0
        launched = False
        while time.monotonic() < deadline:
            if not launched:
                code, out = self.output(launch)
                launched = code == 0 and "launched" in out
            else:
                code, out = self.output(f"cat {d}/{name}.rc 2>/dev/null || true")
                if code == 0 and out.strip():
                    _, text = self.output(f"cat {d}/{name}.log", timeout_s=300)
                    with log.open("a", encoding="utf-8") as f:
                        f.write(text)
                    return int(out.strip())
            failures = failures + 1 if code == 255 else 0
            if failures >= 30:  # about 10 minutes without any SSH connection
                return 255
            time.sleep(poll_s if launched else 5)
        return 124  # timed out; the remote process may still be running until destroy

    def wait_ssh(self, attempts: int = 12) -> None:
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

    def _scp(self, args: list[str], attempts: int = 4) -> None:
        """Copy with retries: the SSH proxy sometimes drops the first connections after start."""
        stderr = ""
        for attempt in range(attempts):
            proc = subprocess.run(
                ["scp", *self.opts, "-P", str(self.target.port), *args],
                capture_output=True,
                text=True,
                timeout=3600,
            )
            if proc.returncode == 0:
                return
            stderr = proc.stderr
            time.sleep(10 * (attempt + 1))
        raise VastError(f"scp failed after {attempts} attempts: {stderr[:300]}")


def _quote(command: str) -> str:
    return "'" + command.replace("'", "'\"'\"'") + "'"
