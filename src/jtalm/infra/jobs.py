"""Job definitions for vast.ai (see jtalm.infra.job for the runner)."""

from jtalm.infra.spec import JobSpec

VLLM_IMAGE = "vllm/vllm-openai:v0.30.0"  # CUDA 13.0, so hosts need cuda_vers >= 13.0
UV = "$HOME/.local/bin/uv"
BASE_QUERY = (
    "num_gpus=1 cuda_vers>=13.0 reliability>0.98 inet_down>=500 disk_space>=120 "
    "rentable=true direct_port_count>=1 verified=true"
)


def start_vllm(model: str, gpu_mem: float, max_len: int, extra: str = "", port: int = 8000) -> str:
    """Start an OpenAI-compatible vLLM server in the background and wait until it is healthy."""
    return (
        'VLLM="$(command -v vllm || echo "python3 -m vllm.entrypoints.cli.main")"; '
        f"setsid nohup $VLLM serve {model} --port {port} --gpu-memory-utilization {gpu_mem} "
        f"--max-model-len {max_len} {extra} > artifacts/vllm-{port}.log 2>&1 < /dev/null & "
        "for i in $(seq 1 180); do "
        f"curl -sf localhost:{port}/health > /dev/null && break; sleep 5; done; "
        f"curl -sf localhost:{port}/health > /dev/null"
    )


SMOKE = JobSpec(
    name="smoke",
    description="M2.5: GPU torch check (train group) and a tiny vLLM generation with Qwen3-0.6B",
    query=f"gpu_ram>=24 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=80,
    max_hours=1.0,
    steps=[
        "nvidia-smi > artifacts/nvidia_smi.txt",
        f"{UV} sync --locked --group train",
        f"{UV} run --group train python -m jtalm.infra.gpu_check > artifacts/gpu_check.json",
        start_vllm("Qwen/Qwen3-0.6B", gpu_mem=0.5, max_len=4096),
        f"{UV} run python -m jtalm.data.smoke_generate --base-url http://localhost:8000/v1 "
        "--model Qwen/Qwen3-0.6B --out artifacts/gen_smoke.jsonl",
    ],
)

JOBS: dict[str, JobSpec] = {job.name: job for job in (SMOKE,)}
