"""Run one job on vast.ai: pick an offer, create, upload code, run, fetch, and always destroy.

Usage (creating an instance costs money, so ``--approve-dph`` is required):

    uv run python -m jtalm.infra.job smoke --approve-dph 0.35

The committed ``HEAD`` is uploaded with ``git archive``; uncommitted changes are not included.
Files listed in ``JobSpec.uploads`` (e.g. gitignored datasets) are copied with scp and checked by
sha256. Credentials in ``.env`` are never uploaded.
Results land in ``runs/vast/<job>-<timestamp>/``.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from jtalm.infra.env import PROJECT_ROOT
from jtalm.infra.jobs import JOBS
from jtalm.infra.spec import JobSpec
from jtalm.infra.vast import Ssh, VastClient, VastError

REMOTE_WORK = "/root/work"
UV_VERSION = "0.12.20"


def remote_bootstrap() -> list[str]:
    """Install a pinned uv and unpack the uploaded code into REMOTE_WORK."""
    return [
        f"curl -LsSf https://astral.sh/uv/{UV_VERSION}/install.sh | sh",
        f"mkdir -p {REMOTE_WORK} && tar -xf /root/code.tar -C {REMOTE_WORK}",
        f"mkdir -p {REMOTE_WORK}/artifacts",
    ]


def _git_archive(dest: Path) -> str:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(dest), "HEAD"], cwd=PROJECT_ROOT, check=True
    )
    return commit


def local_uploads(spec: JobSpec) -> dict[str, str]:
    """sha256 of every upload; fails before any instance is created if a file is missing."""
    digests = {}
    for rel in spec.uploads:
        path = PROJECT_ROOT / rel
        if not path.is_file():
            raise VastError(f"upload not found: {rel}")
        if Path(rel).is_absolute() or ".." in Path(rel).parts or rel.startswith(".env"):
            raise VastError(f"upload must be a project-relative path: {rel}")
        digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def _run_retry(ssh: Ssh, command: str, log: Path, timeout_s: int, attempts: int = 5) -> int:
    """Run a short idempotent command; retry while SSH itself fails (exit 255)."""
    code = 255
    for attempt in range(attempts):
        code = ssh.run(command, log=log, timeout_s=timeout_s)
        if code != 255:
            return code
        time.sleep(10 * (attempt + 1))
    return code


def upload_files(ssh: Ssh, digests: dict[str, str], log: Path) -> None:
    for rel, digest in digests.items():
        remote = f"{REMOTE_WORK}/{rel}"
        if _run_retry(ssh, f"mkdir -p {Path(remote).parent.as_posix()}", log, 60) != 0:
            raise VastError(f"mkdir failed for {rel}")
        ssh.upload(PROJECT_ROOT / rel, remote)
        # 255 means the SSH connection dropped, not a mismatch (train_action_v051, 2026-09-30).
        code = _run_retry(ssh, f"echo '{digest}  {remote}' | sha256sum -c -", log, 300)
        if code != 0:
            raise VastError(f"sha256 check failed ({code}) after upload: {rel}")


STARTUP_ATTEMPTS = 3
STARTUP_TIMEOUT_S = 1800


def _start(
    client: VastClient, spec: JobSpec, offers: list[dict], tmp: Path, attempts: list[dict]
) -> tuple[int, dict, float, dict, Ssh]:
    """Create an instance and wait for SSH, moving to the next offer if a host is too slow.

    Slow image pulls on some hosts kept instances in "loading" for over 20 minutes (2026-09-29),
    so a failed start destroys that instance and tries the next cheapest offer.
    """
    for offer in offers[: STARTUP_ATTEMPTS + 3]:
        if len(attempts) >= STARTUP_ATTEMPTS:
            break
        try:
            instance_id = client.create_instance(
                offer["id"], spec.image, spec.disk_gb, f"jtalm-{spec.name}"
            )
        except VastError as e:  # the offer was taken between search and create; nothing rented
            print(f"offer {offer['id']} unavailable ({str(e)[:120]}); trying the next one")
            continue
        created = time.monotonic()
        print(
            f"created instance {instance_id} on {offer['gpu_name']} at ${offer['dph_total']:.3f}/h"
        )
        try:
            target, info = client.wait_running(instance_id, timeout_s=STARTUP_TIMEOUT_S)
            ssh = Ssh(target, known_hosts=tmp / "known_hosts")
            ssh.wait_ssh()
            return instance_id, offer, created, info, ssh
        except VastError as e:
            destroyed = _destroy(client, instance_id)
            hours = (time.monotonic() - created) / 3600
            attempts.append(
                {
                    "instance_id": instance_id,
                    "offer_id": offer["id"],
                    "gpu_name": offer["gpu_name"],
                    "error": str(e)[:200],
                    "destroyed": destroyed,
                    "hours": round(hours, 3),
                    "cost_usd_estimate": round(hours * offer["dph_total"], 3),
                }
            )
            print(f"start failed on {instance_id} ({e}); destroyed={destroyed}")
    raise VastError(f"no instance started after {len(attempts)} attempts")


def run_job(spec: JobSpec, approve_dph: float, pick: int = 0) -> dict:
    digests = local_uploads(spec)
    client = VastClient()
    offers = [o for o in client.search_offers(spec.query) if o["dph_total"] <= approve_dph]
    if not offers:
        raise VastError(f"no offer under ${approve_dph}/h for: {spec.query}")
    offers = offers[pick:]

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PROJECT_ROOT / "runs" / "vast" / f"{spec.name}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "remote.log"
    record: dict = {"job": asdict(spec), "started_utc": stamp, "uploads": digests}
    attempts: list[dict] = []

    def failed_starts_cost() -> float:
        return sum(a["cost_usd_estimate"] for a in attempts)

    with tempfile.TemporaryDirectory() as tmp:
        tar = Path(tmp) / "code.tar"
        record["commit"] = _git_archive(tar)
        try:
            instance_id, offer, created, info, ssh = _start(
                client, spec, offers, Path(tmp), attempts
            )
        except VastError as e:
            record.update(status=f"failed: {e}", failed_starts=attempts)
            record["cost_usd_estimate"] = round(failed_starts_cost(), 3)
            (out_dir / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            raise
        record["offer"] = {
            k: offer.get(k) for k in ("id", "gpu_name", "gpu_ram", "dph_total", "geolocation")
        }
        record["instance_id"] = instance_id
        record["driver_version"] = info.get("driver_version")
        record["cuda_max_good"] = info.get("cuda_max_good")
        try:
            ssh.upload(tar, "/root/code.tar")
            deadline = created + spec.max_hours * 3600
            boot = remote_bootstrap()
            steps = boot + [f"cd {REMOTE_WORK} && {s}" for s in spec.steps]
            record["steps"] = []
            for n, step in enumerate(steps):
                if n == len(boot):
                    upload_files(ssh, digests, log)
                remaining = int(deadline - time.monotonic())
                if remaining <= 0:
                    raise VastError("max_hours exceeded")
                t0 = time.monotonic()
                code = ssh.run_detached(step, f"step{n:02d}", log, timeout_s=remaining)
                record["steps"].append(
                    {"cmd": step, "exit": code, "sec": round(time.monotonic() - t0)}
                )
                print(f"[{code}] {step[:100]}")
                if code != 0:
                    raise VastError(f"step failed ({code}): {step}")
            for path in spec.fetch:
                ssh.download(f"{REMOTE_WORK}/{path}", out_dir)
            record["status"] = "succeeded"
        except BaseException as e:
            record["status"] = f"failed: {e}"
            _save_debug(client, instance_id, out_dir)
            for path in spec.fetch:  # best effort: keep partial logs for diagnosis
                try:
                    ssh.download(f"{REMOTE_WORK}/{path}", out_dir)
                except Exception as fetch_error:
                    print(f"could not fetch {path}: {fetch_error}")
            raise
        finally:
            record["destroyed"] = _destroy(client, instance_id)
            hours = (time.monotonic() - created) / 3600
            record["hours"] = round(hours, 3)
            record["failed_starts"] = attempts
            record["cost_usd_estimate"] = round(
                hours * offer["dph_total"] + failed_starts_cost(), 3
            )
            (out_dir / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            print(
                f"destroyed={record['destroyed']} hours={record['hours']} "
                f"cost~${record['cost_usd_estimate']} -> {out_dir}"
            )
    return record


def _destroy(client: VastClient, instance_id: int) -> bool:
    """Destroy with retries and confirm it is gone. Never raises, so run.json is always written."""
    for attempt in range(5):
        try:
            client.destroy_instance(instance_id)
            if instance_id not in client.list_instance_ids():
                return True
        except Exception as e:  # keep trying; report below
            print(f"destroy attempt {attempt + 1} failed: {e}")
        time.sleep(10)
    print(f"WARNING: instance {instance_id} may still be running; destroy it manually")
    return False


def _save_debug(client: VastClient, instance_id: int, out_dir: Path) -> None:
    """Best effort: keep the container log for diagnosing failures."""
    try:
        logs = client._run("logs", str(instance_id), "--tail", "200", parse=False)
        (out_dir / "container.log").write_text(logs, encoding="utf-8")
    except Exception as e:
        print(f"could not fetch container logs: {e}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", choices=sorted(JOBS))
    parser.add_argument("--approve-dph", type=float, required=True, help="max $/hour you approve")
    parser.add_argument("--pick", type=int, default=0, help="index among offers under the limit")
    args = parser.parse_args(argv)
    record = run_job(JOBS[args.job], args.approve_dph, args.pick)
    return 0 if record.get("status") == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
