"""Run one job on vast.ai: pick an offer, create, upload code, run, fetch, and always destroy.

Usage (creating an instance costs money, so ``--approve-dph`` is required):

    uv run python -m jtalm.infra.job smoke --approve-dph 0.35

The committed ``HEAD`` is uploaded with ``git archive``; uncommitted changes are not included.
Credentials in ``.env`` are never uploaded. Results land in ``runs/vast/<job>-<timestamp>/``.
"""

import argparse
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


def run_job(spec: JobSpec, approve_dph: float, pick: int = 0) -> dict:
    client = VastClient()
    offers = [o for o in client.search_offers(spec.query) if o["dph_total"] <= approve_dph]
    if not offers:
        raise VastError(f"no offer under ${approve_dph}/h for: {spec.query}")
    offer = offers[pick]

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PROJECT_ROOT / "runs" / "vast" / f"{spec.name}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "remote.log"
    record: dict = {
        "job": asdict(spec),
        "offer": {
            k: offer.get(k) for k in ("id", "gpu_name", "gpu_ram", "dph_total", "geolocation")
        },
        "started_utc": stamp,
    }

    with tempfile.TemporaryDirectory() as tmp:
        tar = Path(tmp) / "code.tar"
        record["commit"] = _git_archive(tar)
        instance_id = client.create_instance(
            offer["id"], spec.image, spec.disk_gb, f"jtalm-{spec.name}"
        )
        record["instance_id"] = instance_id
        created = time.monotonic()
        print(
            f"created instance {instance_id} on {offer['gpu_name']} at ${offer['dph_total']:.3f}/h"
        )
        try:
            target, info = client.wait_running(instance_id)
            record["driver_version"] = info.get("driver_version")
            record["cuda_max_good"] = info.get("cuda_max_good")
            ssh = Ssh(target, known_hosts=Path(tmp) / "known_hosts")
            ssh.wait_ssh()
            ssh.upload(tar, "/root/code.tar")
            deadline = created + spec.max_hours * 3600
            steps = remote_bootstrap() + [f"cd {REMOTE_WORK} && {s}" for s in spec.steps]
            record["steps"] = []
            for step in steps:
                remaining = int(deadline - time.monotonic())
                if remaining <= 0:
                    raise VastError("max_hours exceeded")
                t0 = time.monotonic()
                code = ssh.run(step, log=log, timeout_s=remaining)
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
            raise
        finally:
            client.destroy_instance(instance_id)
            hours = (time.monotonic() - created) / 3600
            record["hours"] = round(hours, 3)
            record["cost_usd_estimate"] = round(hours * offer["dph_total"], 3)
            record["destroyed"] = instance_id not in client.list_instance_ids()
            (out_dir / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            print(
                f"destroyed={record['destroyed']} hours={record['hours']} "
                f"cost~${record['cost_usd_estimate']} -> {out_dir}"
            )
    return record


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
